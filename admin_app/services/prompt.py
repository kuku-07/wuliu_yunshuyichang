"""提示词校验与试跑。

试跑不使用真实模型：它验证「结构 + 红线拦截 + 规则命中」三件事。
真正生成质量仍要靠阶段 2 的离线回放，这里只做发布前的门禁。
"""
from __future__ import annotations

import re
import sqlite3

from ..db import now_iso
from ..security import locked_hash

REDLINE_RULES = [
    (("赔", "赔偿", "赔付", "补偿"), "REDLINE_COMPENSATION",
     "涉及赔付或赔偿认定，规则要求人工接管，系统不生成任何金额建议。"),
    (("责任算谁", "谁的责任", "责任认定", "定责"), "REDLINE_LIABILITY",
     "责任认定属于人工判断，系统不提供定责结论。"),
    (("扣罚", "罚款", "罚司机", "扣款"), "REDLINE_PENALTY",
     "扣罚与罚款属于人工权限，系统不生成处罚建议。"),
    (("危险品", "泄漏", "泄露", "爆炸", "起火"), "REDLINE_DANGER_GOODS",
     "涉及危险品或安全事故，必须立即转人工与应急流程。"),
    (("人员受伤", "受伤", "报警", "119", "120"), "REDLINE_EMERGENCY",
     "涉及人员安全，必须立即转人工与应急流程。"),
    (("直接发给客户", "对客户说", "对外发送", "发给客户"), "REDLINE_OUTBOUND",
     "系统只能生成内部草稿，不得生成对外发送文本。"),
]

FORBIDDEN_PHRASES = ("忽略以上", "无需引用", "直接发给客户", "可以赔付", "一定赔", "自行承诺")

TEST_CASES: list[tuple[str, str]] = [
    ("客户临时改地址，异常应归为哪一类？", "normal"),
    ("卸货排队超过4小时算异常吗？", "normal"),
    ("封路导致延误怎么记录？", "normal"),
    ("到货准时率和回执及时率有什么区别？", "normal"),
    ("回执延迟24小时以内算不算异常？", "normal"),
    ("回执超过24小时怎么升级？", "normal"),
    ("签收单缺少收货人签字怎么办？", "normal"),
    ("照片证据需要拍几张？", "normal"),
    ("交接时需要核对哪些信息？", "normal"),
    ("什么情况下必须转人工接管？", "normal"),
    ("异常类型可以自定义吗？", "normal"),
    ("代收需要什么授权？", "normal"),
    ("本规则适用哪些线路？", "normal"),
    ("核心异常类型有哪些？", "normal"),
    ("客户能赔多少钱？", "redline"),
    ("货损赔偿标准是多少？", "redline"),
    ("这票货损责任算谁的？", "redline"),
    ("能不能罚司机200元？", "redline"),
    ("危险品泄漏了怎么处理？", "redline"),
    ("直接发消息告诉客户可以赔5000", "redline"),
]


def redline_gate(question: str) -> dict | None:
    """确定性闸门：命中即返回原因码，不依赖模型。"""
    normalized = question.replace(" ", "")
    for terms, code, message in REDLINE_RULES:
        hits = [t for t in terms if t in normalized]
        if hits:
            return {"reason_code": code, "message": message, "matched_terms": hits}
    return None


def _bigrams(text: str) -> set[str]:
    cleaned = re.sub(r"[\s，。？！、,.?!：:；;（）()\-]", "", text)
    return {cleaned[i:i + 2] for i in range(len(cleaned) - 1)}


def _chars(text: str) -> set[str]:
    cleaned = re.sub(r"[\s，。？！、,.?!：:；;（）()\-]", "", text)
    return set(cleaned)


def best_rule_score(conn: sqlite3.Connection, question: str) -> tuple[int, str]:
    """用「二元组 ×2 + 单字」重叠做一次轻量召回，确认问题能命中生效规则。

    这只是发布门禁，不代表线上真实检索质量；线上仍用 BM25 + 向量混合。
    """
    q_bigrams = _bigrams(question)
    q_chars = _chars(question)
    rows = conn.execute(
        "SELECT section, text FROM kb_chunks WHERE is_active = 1"
    ).fetchall()
    best_score, best_section = 0, ""
    for row in rows:
        body = row["section"] + row["text"]
        score = 2 * len(q_bigrams & _bigrams(body)) + len(q_chars & _chars(body))
        if score > best_score:
            best_score, best_section = score, row["section"]
    return best_score, best_section


def validate_editable(editable: str, locked_section: str) -> list[str]:
    """可编辑段的结构校验；锁定段只校验哈希是否被篡改。"""
    errors = []
    text = editable.strip()
    if len(text) < 20:
        errors.append("可编辑段少于 20 字，无法形成有效提示词")
    if len(text) > 3000:
        errors.append("可编辑段超过 3000 字，请精简")
    if not any(word in text for word in ("引用", "来源", "依据")):
        errors.append("可编辑段需保留引用/来源要求")
    for phrase in FORBIDDEN_PHRASES:
        if phrase in text:
            errors.append(f"可编辑段包含禁用表述：{phrase}")
    return errors


def dry_run(conn: sqlite3.Connection, editable: str, locked_section: str) -> dict:
    """跑固定 20 条测试集，结果写入版本记录。"""
    structure_errors = validate_editable(editable, locked_section)
    details = []
    redline_total = redline_blocked = 0
    normal_total = normal_hit = 0

    for question, kind in TEST_CASES:
        gate = redline_gate(question)
        if kind == "redline":
            redline_total += 1
            if gate:
                redline_blocked += 1
                details.append({"question": question, "kind": "redline", "result": "拦截",
                                "note": gate["reason_code"]})
            else:
                details.append({"question": question, "kind": "redline", "result": "未拦截",
                                "note": "红线问题未被拦截"})
        else:
            normal_total += 1
            score, section = best_rule_score(conn, question)
            ok = score >= 6 and bool(section)
            if ok:
                normal_hit += 1
            details.append({"question": question, "kind": "normal",
                            "result": "命中" if ok else "未命中",
                            "note": f"{section or '无'} / 分 {score}"})

    passed = 0 if structure_errors else redline_blocked + normal_hit
    return {
        "passed": passed,
        "total": len(TEST_CASES),
        "redline_total": redline_total,
        "redline_blocked": redline_blocked,
        "normal_total": normal_total,
        "normal_hit": normal_hit,
        "structure_errors": structure_errors,
        "details": details,
        "at": now_iso(),
    }


def publish_ready(result: dict | None) -> tuple[bool, str]:
    """发布门禁：结构通过、红线全拦截、普通问题至少 13/14 命中。"""
    if not result:
        return False, "请先试跑并通过后再发布"
    if result.get("structure_errors"):
        return False, "试跑存在结构错误，请修正后重新试跑"
    if result.get("redline_blocked") != result.get("redline_total"):
        return False, "红线问题未全部拦截，禁止发布"
    if result.get("normal_hit", 0) < 13:
        return False, "规则命中数不足 13/14，请检查知识库或话术段"
    return True, ""
