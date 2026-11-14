"""契约版本导入与逐字段兼容性比较。

职责拆分：
- ``parse_contract``：解析并校验上传的契约文件内容，格式错误抛 ``ContractFormatError``，
  调用方据此保留原契约、不落任何批次；
- ``fingerprint``：对规范化后的契约算 SHA-256 指纹，相同指纹重复上传直接返回历史批次；
- ``compare_side``：对请求参数 / 响应字段分别做逐字段比较，识别新增、删除、类型变化、顺序调整；
- ``ContractRepository``：保存每个接口编号的最新字段快照与全部比较批次，
  数据接口契约模块与调用来源管理模块共用同一份兼容性结论。
"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any

# 兼容结论取值，汇总顺序即优先级：出现不兼容直接判不兼容，其次不可判定，否则兼容。
COMPATIBLE = "兼容"
INCOMPATIBLE = "不兼容"
UNDECIDABLE = "不可判定"

# 变更种类（请求侧 / 响应侧共用名称，side 字段区分方向）。
KIND_ADDED = "新增字段"
KIND_REMOVED = "删除字段"
KIND_TYPE_CHANGED = "类型变化"
KIND_REORDERED = "顺序调整"

SIDE_REQUEST = "请求参数"
SIDE_RESPONSE = "响应字段"


class ContractFormatError(ValueError):
    """契约文件格式错误：此时不得写入批次或覆盖快照，原契约保持不变。"""


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def parse_contract(content: str, filename: str | None = None) -> dict[str, Any]:
    """解析上传的契约文本并做结构校验。

    契约格式（JSON）::

        {
          "接口编号": "SCHE-0002",
          "契约版本": "v2",
          "请求参数": [{"名称": "userId", "类型": "string", "必填": true}],
          "响应字段": [{"名称": "orderId", "类型": "string", "必填": false}]
        }

    任一项不满足结构要求都抛 ``ContractFormatError``；字段的“类型”允许缺失，
    缺失类型会在比较阶段判为不可判定，而不是在这里拒绝文件。
    """
    source = f"文件「{filename}」" if filename else "上传内容"
    if not str(content or "").strip():
        raise ContractFormatError(f"{source}为空，未导入任何契约")
    try:
        raw = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ContractFormatError(f"{source}不是合法 JSON：第 {exc.lineno} 行第 {exc.colno} 列附近解析失败") from exc
    if not isinstance(raw, dict):
        raise ContractFormatError(f"{source}根节点必须是 JSON 对象，当前为 {type(raw).__name__}")

    interface_code = str(raw.get("接口编号") or "").strip()
    if not interface_code:
        raise ContractFormatError(f"{source}缺少必填的「接口编号」，无法归属到具体接口")

    version = raw.get("契约版本")
    version = str(version).strip() if version not in (None, "") else "未标注版本"

    return {
        "接口编号": interface_code,
        "契约版本": version,
        "请求参数": _parse_field_list(raw.get(SIDE_REQUEST), SIDE_REQUEST, source),
        "响应字段": _parse_field_list(raw.get(SIDE_RESPONSE), SIDE_RESPONSE, source),
    }


def _parse_field_list(value: Any, side: str, source: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ContractFormatError(f"{source}的「{side}」必须是字段数组，当前为 {type(value).__name__}")
    fields: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            raise ContractFormatError(f"{source}的「{side}」第 {index + 1} 项必须是字段对象")
        name = str(item.get("名称") or "").strip()
        if not name:
            raise ContractFormatError(f"{source}的「{side}」第 {index + 1} 项缺少非空「名称」")
        if name in seen:
            raise ContractFormatError(f"{source}的「{side}」中字段「{name}」重复定义")
        seen.add(name)
        required = item.get("必填", False)
        if not isinstance(required, bool):
            raise ContractFormatError(f"{source}的「{side}」字段「{name}」的「必填」必须是布尔值")
        field_type = item.get("类型")
        field_type = str(field_type).strip() if field_type not in (None, "") else ""
        fields.append({"名称": name, "类型": field_type, "必填": required})
    return fields


def fingerprint(contract: dict[str, Any]) -> str:
    """对契约的业务内容算稳定指纹：排序键、去空白，保证同内容同指纹。"""
    payload = {
        "接口编号": contract["接口编号"],
        "契约版本": contract["契约版本"],
        "请求参数": contract["请求参数"],
        "响应字段": contract["响应字段"],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _judge(kind: str, side: str, field: dict[str, Any], old_type: str, new_type: str) -> tuple[str, str]:
    """按变更种类给出单字段兼容性结论与可读理由。"""
    name = field["名称"]
    if kind == KIND_ADDED:
        if side == SIDE_REQUEST and field.get("必填"):
            return INCOMPATIBLE, f"新增必填请求参数「{name}」，旧调用方不会上送该参数，调用失配"
        if side == SIDE_REQUEST:
            return COMPATIBLE, f"新增可选请求参数「{name}」，旧调用方不上送也能继续调用"
        return COMPATIBLE, f"新增响应字段「{name}」，旧调用方忽略多余字段即可"

    if kind == KIND_REMOVED:
        if side == SIDE_RESPONSE and field.get("必填"):
            return INCOMPATIBLE, f"删除必填响应字段「{name}」，旧调用方读取时会缺失关键字段"
        if side == SIDE_RESPONSE:
            return COMPATIBLE, f"删除可选响应字段「{name}」，旧调用方对可选字段本就允许缺失"
        return COMPATIBLE, f"删除请求参数「{name}」，旧调用方继续上送不会影响服务端解析"

    if kind == KIND_REORDERED:
        return COMPATIBLE, f"字段「{name}」仅发生顺序调整，名称与类型均未变化"

    # 类型变化：任一侧类型缺失则无法确认是否兼容。
    if not old_type or not new_type:
        return UNDECIDABLE, (
            f"字段「{name}」发生类型变化但类型信息缺失（旧类型={old_type or '缺失'}，"
            f"新类型={new_type or '缺失'}），无法判定旧调用方是否失配"
        )
    return INCOMPATIBLE, f"字段「{name}」类型由 {old_type} 变为 {new_type}，旧调用方按原类型解析会失配"


def compare_side(old_fields: list[dict[str, Any]], new_fields: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
    """逐字段比较单侧（请求参数或响应字段），返回带兼容性结论的变更明细。"""
    old_index = {field["名称"]: idx for idx, field in enumerate(old_fields)}
    new_index = {field["名称"]: idx for idx, field in enumerate(new_fields)}
    old_by_name = {field["名称"]: field for field in old_fields}
    new_by_name = {field["名称"]: field for field in new_fields}
    changes: list[dict[str, Any]] = []

    for name, idx in new_index.items():
        if name not in old_index:
            field = new_by_name[name]
            verdict, reason = _judge(KIND_ADDED, side, field, "", field["类型"])
            changes.append(_change(side, KIND_ADDED, name, None, idx, "", field["类型"],
                                   field.get("必填", False), verdict, reason))

    for name, idx in old_index.items():
        if name not in new_index:
            field = old_by_name[name]
            verdict, reason = _judge(KIND_REMOVED, side, field, field["类型"], "")
            changes.append(_change(side, KIND_REMOVED, name, idx, None, field["类型"], "",
                                   field.get("必填", False), verdict, reason))

    for name in new_index.keys() & old_index.keys():
        old_field, new_field = old_by_name[name], new_by_name[name]
        old_pos, new_pos = old_index[name], new_index[name]
        if old_field["类型"] != new_field["类型"]:
            verdict, reason = _judge(KIND_TYPE_CHANGED, side, new_field, old_field["类型"], new_field["类型"])
            changes.append(_change(side, KIND_TYPE_CHANGED, name, old_pos, new_pos,
                                   old_field["类型"], new_field["类型"],
                                   new_field.get("必填", False), verdict, reason))
        elif old_pos != new_pos:
            verdict, reason = _judge(KIND_REORDERED, side, new_field, old_field["类型"], new_field["类型"])
            changes.append(_change(side, KIND_REORDERED, name, old_pos, new_pos,
                                   old_field["类型"], new_field["类型"],
                                   new_field.get("必填", False), verdict, reason))
    return changes


def _change(side: str, kind: str, field_name: str,
            old_pos: int | None, new_pos: int | None,
            old_type: str, new_type: str, required: bool,
            verdict: str, reason: str) -> dict[str, Any]:
    return {
        "方向": side,
        "变更种类": kind,
        "字段名称": field_name,
        "旧类型": old_type,
        "新类型": new_type,
        "旧位置": old_pos,
        "新位置": new_pos,
        "必填": bool(required),
        "兼容结论": verdict,
        "判定理由": reason,
    }


def summarize(changes: list[dict[str, Any]]) -> str:
    """把逐字段结论汇总成批次级结论。"""
    verdicts = {change["兼容结论"] for change in changes}
    if INCOMPATIBLE in verdicts:
        return INCOMPATIBLE
    if UNDECIDABLE in verdicts:
        return UNDECIDABLE
    return COMPATIBLE


class ContractRepository:
    """契约批次与字段快照的内存仓库，跨模块共享同一份兼容性结论。"""

    def __init__(self) -> None:
        self._batches: list[dict[str, Any]] = []
        self._snapshots: dict[str, dict[str, list[dict[str, Any]]]] = {}
        self._fingerprints: dict[tuple[str, str], int] = {}
        self._seq = 0

    def import_contract(self, content: str, filename: str | None = None) -> dict[str, Any]:
        contract = parse_contract(content, filename)
        interface_code = contract["接口编号"]
        digest = fingerprint(contract)

        existing_id = self._fingerprints.get((interface_code, digest))
        if existing_id is not None:
            reused = copy.deepcopy(self._find_by_id(existing_id))
            reused["复用"] = True
            reused["提示"] = "契约指纹与历史批次一致，直接返回已有批次，未重复生成快照"
            return reused

        previous = self._snapshots.get(interface_code)
        if previous is None:
            changes: list[dict[str, Any]] = []
            verdict = COMPATIBLE
            summary_note = "首次导入该接口契约，已生成请求参数与响应字段快照，暂无历史版本可比较"
        else:
            changes = compare_side(previous["请求参数"], contract["请求参数"], SIDE_REQUEST)
            changes += compare_side(previous["响应字段"], contract["响应字段"], SIDE_RESPONSE)
            verdict = summarize(changes)
            summary_note = ""

        self._seq += 1
        batch = {
            "id": self._seq,
            "批次编号": f"CONT-{self._seq:04d}",
            "接口编号": interface_code,
            "契约版本": contract["契约版本"],
            "文件名": filename or "手动粘贴",
            "指纹": digest,
            "导入时间": _now_text(),
            "复用": False,
            "兼容结论": verdict,
            "变化字段数": len(changes),
            "变更明细": changes,
            "快照": {
                SIDE_REQUEST: copy.deepcopy(contract["请求参数"]),
                SIDE_RESPONSE: copy.deepcopy(contract["响应字段"]),
            },
        }
        if summary_note:
            batch["说明"] = summary_note
        self._batches.append(batch)
        self._snapshots[interface_code] = copy.deepcopy(batch["快照"])
        self._fingerprints[(interface_code, digest)] = batch["id"]
        return copy.deepcopy(batch)

    def list_batches(self, interface_code: str | None = None) -> list[dict[str, Any]]:
        batches = self._batches
        if interface_code:
            code = interface_code.strip()
            batches = [batch for batch in batches if batch["接口编号"] == code]
        return [copy.deepcopy(batch) for batch in batches]

    def get_batch(self, batch_id: int) -> dict[str, Any] | None:
        batch = self._find_by_id(batch_id)
        return copy.deepcopy(batch) if batch else None

    def latest_compatibility(self, interface_code: str) -> dict[str, Any] | None:
        """供调用来源管理按接口编号读取同一兼容性结论。"""
        code = interface_code.strip()
        for batch in reversed(self._batches):
            if batch["接口编号"] == code:
                view = copy.deepcopy(batch)
                view.pop("快照", None)
                return view
        return None

    def _find_by_id(self, batch_id: int) -> dict[str, Any] | None:
        for batch in self._batches:
            if batch["id"] == batch_id:
                return batch
        return None


# 进程级单例：schema 模块写入、whitelist 模块读取，保证两边拿到的是同一份结论。
contract_repository = ContractRepository()
