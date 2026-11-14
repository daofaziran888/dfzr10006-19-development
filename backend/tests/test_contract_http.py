"""通过真实 HTTP 接口验证契约导入、指纹复用、来源侧同源结论与格式错误保护。

运行（需先启动 uvicorn）：
  backend/.venv/bin/python -I tests/test_contract_http.py
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8011"


def call(method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read().decode("utf-8"))


def check(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)
    print(f"  ✓ {message}")


def contract(code: str, version: str, req: list, resp: list) -> str:
    return json.dumps({"接口编号": code, "契约版本": version,
                       "请求参数": req, "响应字段": resp}, ensure_ascii=False)


def main() -> None:
    print("[A] 首次导入 SCHE-0002 生成快照")
    v1 = contract("SCHE-0002", "v1",
                  [{"名称": "userId", "类型": "string", "必填": True}],
                  [{"名称": "orderId", "类型": "string", "必填": True},
                   {"名称": "coupon", "类型": "string", "必填": False}])
    status, payload = call("POST", "/api/schema/contracts/import",
                           {"content": v1, "filename": "sche0002-v1.json"})
    check(status == 200 and payload["ok"] is True, "导入接口返回 200")
    first = payload["batch"]
    check(first["变化字段数"] == 0, "首次导入无变化字段")
    check(len(first["快照"]["响应字段"]) == 2, "响应字段快照已生成")
    check(first["兼容结论"] == "兼容", "基线批次判兼容")

    print("[B] 第二次导入：新增必填请求参数 + 删除可选响应字段 + 顺序调整")
    v2 = contract("SCHE-0002", "v2",
                  [{"名称": "userId", "类型": "string", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True}],
                  [{"名称": "orderId", "类型": "string", "必填": True}])
    status, payload = call("POST", "/api/schema/contracts/import",
                           {"content": v2, "filename": "sche0002-v2.json"})
    second = payload["batch"]
    by = {(c["方向"], c["变更种类"], c["字段名称"]): c for c in second["变更明细"]}
    check(by[("请求参数", "新增字段", "tenantId")]["兼容结论"] == "不兼容", "新增必填请求参数判不兼容")
    check(by[("响应字段", "删除字段", "coupon")]["兼容结论"] == "兼容", "删除可选响应字段判兼容")
    check(second["兼容结论"] == "不兼容", "批次整体判不兼容")

    print("[C] 相同指纹再次上传，返回已有批次且只报告原变化字段")
    status, payload = call("POST", "/api/schema/contracts/import",
                           {"content": v2, "filename": "sche0002-v2-dup.json"})
    check(payload["batch"]["复用"] is True, "标记为复用批次")
    check(payload["batch"]["id"] == second["id"], "返回同一个批次 id")
    check(payload["batch"]["变化字段数"] == second["变化字段数"], "仍只报告原变化字段")

    print("[D] 类型变化且类型缺失 → 不可判定")
    v3 = contract("SCHE-0002", "v3",
                  [{"名称": "userId", "类型": "", "必填": True},
                   {"名称": "tenantId", "类型": "string", "必填": True}],
                  [{"名称": "orderId", "类型": "string", "必填": True}])
    status, payload = call("POST", "/api/schema/contracts/import", {"content": v3})
    check(payload["batch"]["兼容结论"] == "不可判定", "缺失类型汇总为不可判定")
    undecided = next(c for c in payload["batch"]["变更明细"] if c["字段名称"] == "userId")
    check(undecided["兼容结论"] == "不可判定" and "缺失" in undecided["判定理由"], "单字段给出缺失类型理由")

    print("[E] 批次列表与单批次查询")
    status, payload = call("GET", "/api/schema/contracts?interface_code=SCHE-0002")
    check(status == 200 and payload["total"] == 3, "按接口编号查到 3 个批次（复用不新增）")
    status, payload = call("GET", f"/api/schema/contracts/{first['id']}")
    check(status == 200 and payload["批次编号"] == first["批次编号"], "单批次详情可读")
    status, _ = call("GET", "/api/schema/contracts/9999")
    check(status == 404, "不存在的批次返回 404")

    print("[F] 调用来源管理按接口编号读取同一兼容性结论")
    _, schema_view = call("GET", "/api/schema/contracts?interface_code=SCHE-0002")
    latest_id = schema_view["items"][-1]["id"]
    status, payload = call("GET", "/api/whitelist/compatibility?interface_code=SCHE-0002")
    check(status == 200 and payload["有结论"] is True, "来源侧查到结论")
    check(payload["batch"]["id"] == latest_id, "结论来自契约模块同一最新批次")
    check("快照" not in payload["batch"], "来源侧不暴露字段快照")
    status, payload = call("GET", "/api/whitelist/compatibility?interface_code=SCHE-4040")
    check(status == 200 and payload["有结论"] is False, "未导入接口返回无结论而非报错")

    print("[G] 文件格式错误返回 400，原契约保留")
    bad_cases = ["", "{broken json", json.dumps({"契约版本": "x"}, ensure_ascii=False)]
    for bad in bad_cases:
        status, payload = call("POST", "/api/schema/contracts/import", {"content": bad, "filename": "bad.json"})
        check(status == 400 and payload["detail"]["契约保留"] is True, "格式错误返回 400 且声明原契约保留")
    status, payload = call("GET", "/api/schema/contracts?interface_code=SCHE-0002")
    check(payload["total"] == 3, "错误文件没有产生任何批次")
    status, payload = call("GET", "/api/whitelist/compatibility?interface_code=SCHE-0002")
    check(payload["batch"]["兼容结论"] == "不可判定", "来源侧结论未被错误文件污染")

    print("\nHTTP 端到端验证全部通过。")


if __name__ == "__main__":
    sys.exit(main())
