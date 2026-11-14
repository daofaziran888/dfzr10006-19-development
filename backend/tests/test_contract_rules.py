"""契约导入与逐字段比较的端到端规则验证（纯断言脚本，不依赖 pytest）。

运行：backend/.venv/bin/python -I tests/test_contract_rules.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.contracts import (
    COMPATIBLE,
    INCOMPATIBLE,
    UNDECIDABLE,
    ContractFormatError,
    ContractRepository,
    parse_contract,
)


def contract(code: str, version: str, request_fields: list, response_fields: list) -> str:
    import json

    return json.dumps(
        {"接口编号": code, "契约版本": version,
         "请求参数": request_fields, "响应字段": response_fields},
        ensure_ascii=False,
    )


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def main() -> None:
    print("[1] 首次导入生成快照，无变更明细")
    repo = ContractRepository()
    v1 = contract("SCHE-0002", "v1",
                  [{"名称": "userId", "类型": "string", "必填": True}],
                  [{"名称": "orderId", "类型": "string", "必填": True},
                   {"名称": "coupon", "类型": "string", "必填": False}])
    first = repo.import_contract(v1, "sche-0002-v1.json")
    check(first["兼容结论"] == COMPATIBLE, "首次导入判兼容（基线）")
    check(first["变化字段数"] == 0 and first["变更明细"] == [], "首次导入无变更明细")
    check(len(first["快照"]["响应字段"]) == 2, "首次导入生成响应字段快照")
    check(first["批次编号"] == "CONT-0001", "批次编号自增生成")

    print("[2] 新增必填请求参数判不兼容；删除可选响应字段判兼容；顺序调整判兼容")
    v2 = contract("SCHE-0002", "v2",
                  [{"名称": "userId", "类型": "string", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True}],
                  [{"名称": "orderId", "类型": "string", "必填": True}])
    second = repo.import_contract(v2, "sche-0002-v2.json")
    kinds = {(c["方向"], c["变更种类"], c["字段名称"]): c for c in second["变更明细"]}
    check(second["兼容结论"] == INCOMPATIBLE, "批次整体判不兼容")
    added = kinds[("请求参数", "新增字段", "tenantId")]
    check(added["兼容结论"] == INCOMPATIBLE, "新增必填请求参数判不兼容")
    removed = kinds[("响应字段", "删除字段", "coupon")]
    check(removed["兼容结论"] == COMPATIBLE, "删除可选响应字段判兼容")
    check(second["变化字段数"] == 2, "只报告发生变化的字段（userId、orderId 未变不报告）")

    print("[2b] 仅调整字段顺序，名称与类型不变，判兼容")
    reorder_v1 = contract("SCHE-0007", "v1",
                          [{"名称": "a", "类型": "string", "必填": False}],
                          [{"名称": "x", "类型": "string", "必填": False},
                           {"名称": "y", "类型": "number", "必填": False}])
    repo.import_contract(reorder_v1)
    reorder_v2 = contract("SCHE-0007", "v2",
                          [{"名称": "a", "类型": "string", "必填": False}],
                          [{"名称": "y", "类型": "number", "必填": False},
                           {"名称": "x", "类型": "string", "必填": False}])
    reorder_batch = repo.import_contract(reorder_v2)
    check(reorder_batch["变化字段数"] == 2, "两个字段的位置都发生变化")
    check(all(c["变更种类"] == "顺序调整" and c["兼容结论"] == COMPATIBLE
              for c in reorder_batch["变更明细"]), "顺序调整全部判兼容")
    check(reorder_batch["兼容结论"] == COMPATIBLE, "纯顺序调整的批次判兼容")

    print("[3] 相同指纹重复上传返回已有批次，不新增快照")
    batch_count_before = len(repo.list_batches())
    reused = repo.import_contract(v2, "sche-0002-v2-copy.json")
    check(reused["复用"] is True, "重复指纹标记为复用")
    check(reused["id"] == second["id"], "复用返回同一批次 id")
    check(len(repo.list_batches()) == batch_count_before, "复用没有新增批次")
    check(len(reused["变更明细"]) == second["变化字段数"], "复用批次仍只报告原变化字段")

    print("[4] 类型变化且双方都有类型判不兼容")
    v3 = contract("SCHE-0002", "v3",
                  [{"名称": "userId", "类型": "number", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True}],
                  [{"名称": "coupon", "类型": "string", "必填": False},
                   {"名称": "orderId", "类型": "string", "必填": True}])
    third = repo.import_contract(v3, "sche-0002-v3.json")
    type_change = next(c for c in third["变更明细"]
                       if c["变更种类"] == "类型变化" and c["字段名称"] == "userId")
    check(type_change["兼容结论"] == INCOMPATIBLE, "string→number 判不兼容")
    check(type_change["旧类型"] == "string" and type_change["新类型"] == "number", "记录新旧类型")

    print("[5] 缺失类型标为不可判定")
    v4 = contract("SCHE-0002", "v4",
                  [{"名称": "userId", "类型": "", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True}],
                  [{"名称": "coupon", "类型": "string", "必填": False},
                   {"名称": "orderId", "类型": "string", "必填": True}])
    fourth = repo.import_contract(v4, "sche-0002-v4.json")
    undecided = next(c for c in fourth["变更明细"] if c["字段名称"] == "userId")
    check(undecided["兼容结论"] == UNDECIDABLE, "新类型缺失判不可判定")
    check(fourth["兼容结论"] == UNDECIDABLE, "批次汇总为不可判定")

    print("[6] 新增可选请求参数判兼容；删除必填响应字段判不兼容")
    v5 = contract("SCHE-0002", "v5",
                  [{"名称": "userId", "类型": "", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True},
                   {"名称": "traceId", "类型": "string", "必填": False}],
                  [{"名称": "coupon", "类型": "string", "必填": False}])
    fifth = repo.import_contract(v5, "sche-0002-v5.json")
    opt_added = next(c for c in fifth["变更明细"]
                     if c["变更种类"] == "新增字段" and c["字段名称"] == "traceId")
    required_removed = next(c for c in fifth["变更明细"]
                            if c["变更种类"] == "删除字段" and c["字段名称"] == "orderId")
    check(opt_added["兼容结论"] == COMPATIBLE, "新增可选请求参数判兼容")
    check(required_removed["兼容结论"] == INCOMPATIBLE, "删除必填响应字段判不兼容")

    print("[7] 调用来源按接口编号读取同一结论")
    view = repo.latest_compatibility("SCHE-0002")
    check(view is not None and view["id"] == fifth["id"], "读到该接口最新批次")
    check("快照" not in view, "来源侧结论不带快照，只看兼容性判断")
    check(repo.latest_compatibility("SCHE-9999") is None, "未导入的接口返回无结论")

    print("[8] 文件格式错误保留原契约")
    before = len(repo.list_batches())
    for bad, hint in [
        ("", "空内容"),
        ("{not json", "非法 JSON"),
        ('{"契约版本": "v9"}', "缺接口编号"),
        ('{"接口编号": "SCHE-0002", "请求参数": {}}', "字段数组写成对象"),
        ('{"接口编号": "SCHE-0002", "响应字段": [{"类型": "string"}]}', "字段缺名称"),
        ('{"接口编号": "SCHE-0002", "请求参数": [{"名称": "a", "必填": "yes"}]}', "必填非布尔"),
    ]:
        try:
            parse_contract(bad, "bad.json")
        except ContractFormatError:
            print(f"  ✓ 拒绝格式错误文件（{hint}）")
        else:
            raise AssertionError(f"本应拒绝的格式错误未被拦截：{hint}")
    check(len(repo.list_batches()) == before, "格式错误未产生任何批次，原契约保留")

    accepted = parse_contract('{"接口编号": "SCHE-0002", "请求参数": []}', "partial.json")
    check(accepted["响应字段"] == [], "缺省的响应字段键按空数组处理，不视为格式错误")

    print("\n全部规则验证通过。")


if __name__ == "__main__":
    sys.exit(main())
