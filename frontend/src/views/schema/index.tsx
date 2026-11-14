import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/schema'
const columns = [
  "接口编号",
  "接口名称",
  "请求方法",
  "请求参数",
  "响应字段",
  "字段类型",
  "契约版本",
  "接口状态"
]
const actions = [
  "发布契约",
  "废弃接口",
  "冻结接口"
]
const statuses = [
  "草稿",
  "已发布",
  "已废弃",
  "已冻结"
]
const stats = [
  {
    "label": "接口定义总数",
    "value": 0
  },
  {
    "label": "已发布接口",
    "value": 0
  },
  {
    "label": "已废弃接口",
    "value": 0
  }
]

type Row = Record<string, string | number | null>
type Verdict = '兼容' | '不兼容' | '不可判定'

interface FieldChange {
  方向: string
  变更种类: string
  字段名称: string
  旧类型: string
  新类型: string
  旧位置: number | null
  新位置: number | null
  必填: boolean
  兼容结论: Verdict
  判定理由: string
}

interface ContractBatch {
  id: number
  批次编号: string
  接口编号: string
  契约版本: string
  文件名: string
  指纹: string
  导入时间: string
  复用: boolean
  兼容结论: Verdict
  变化字段数: number
  变更明细: FieldChange[]
  说明?: string
  提示?: string
}

const SAMPLE_CONTRACT = `{
  "接口编号": "SCHE-0002",
  "契约版本": "v2",
  "请求参数": [
    { "名称": "userId", "类型": "string", "必填": true },
    { "名称": "tenantId", "类型": "string", "必填": true }
  ],
  "响应字段": [
    { "名称": "orderId", "类型": "string", "必填": true }
  ]
}`

function verdictClass(verdict: string): string {
  if (verdict === '兼容') return 'badge compatible'
  if (verdict === '不兼容') return 'badge incompatible'
  if (verdict === '不可判定') return 'badge undecidable'
  return 'badge neutral'
}

export default function SchemaView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const [contractText, setContractText] = useState(SAMPLE_CONTRACT)
  const [fileName, setFileName] = useState('')
  const [importing, setImporting] = useState(false)
  const [importMessage, setImportMessage] = useState('')
  const [batches, setBatches] = useState<ContractBatch[]>([])
  const [batchFilter, setBatchFilter] = useState('SCHE-0002')
  const [expanded, setExpanded] = useState<number | null>(null)

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('接口定义列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据接口契约列表读取失败')
    }
  }, [filters])

  const reloadBatches = useCallback(async (code: string) => {
    const query = code.trim() ? `?interface_code=${encodeURIComponent(code.trim())}` : ''
    try {
      const response = await request(`${ENDPOINT}/contracts${query}`)
      if (!response.ok) {
        throw new Error('契约批次读取失败')
      }
      const payload = await response.json()
      setBatches(payload.items ?? [])
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '契约批次读取失败')
    }
  }, [])

  useEffect(() => {
    void reload()
  }, [reload])

  useEffect(() => {
    void reloadBatches(batchFilter)
  }, [reloadBatches, batchFilter])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('数据接口契约动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '数据接口契约操作失败')
    }
  }

  async function importContract() {
    setErrorMessage('')
    setImportMessage('')
    setImporting(true)
    try {
      const response = await request(`${ENDPOINT}/contracts/import`, {
        method: 'POST',
        body: JSON.stringify({ content: contractText, filename: fileName.trim() || undefined }),
      })
      const payload = await response.json()
      if (!response.ok) {
        const detail = payload?.detail
        const message = typeof detail === 'object' && detail !== null ? detail.message : '契约文件格式错误'
        throw new Error(message)
      }
      const batch = payload.batch as ContractBatch
      setImportMessage(
        batch.复用
          ? `契约指纹重复，已返回历史批次 ${batch.批次编号}，未重复生成快照`
          : `批次 ${batch.批次编号} 已生成，整体结论：${batch.兼容结论}，变化字段 ${batch.变化字段数} 个`,
      )
      setExpanded(batch.id)
      await reloadBatches(batchFilter)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '契约导入失败，原契约已保留')
    } finally {
      setImporting(false)
    }
  }

  return (
    <section className="page" data-module="schema">
      <header className="page-head">
        <div>
          <h2>数据接口契约管理</h2>
          <p className="page-desc">维护数据接口的请求参数、响应字段与契约版本管理，为数据接口契约提供可审计的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('接口定义登记入口尚未接入审批流')}>
            登记接口定义
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出数据接口契约清单
          </button>
        </div>
      </header>

      <div className="panel">
        <div className="panel-head">
          <h3 className="panel-title">契约版本导入与逐字段兼容性比较</h3>
        </div>
        <p className="panel-hint">
          粘贴契约 JSON（含接口编号、契约版本、请求参数、响应字段；字段支持名称、类型、必填）。
          首次导入生成字段快照；相同契约指纹重复上传直接返回历史批次；文件格式错误会拒绝导入并保留原契约。
        </p>
        <textarea
          className="contract-textarea"
          value={contractText}
          onChange={(event) => setContractText(event.target.value)}
          spellCheck={false}
        />
        <div className="form-row">
          <input
            className="inline-input"
            placeholder="来源文件名（可选，用于错误定位）"
            value={fileName}
            onChange={(event) => setFileName(event.target.value)}
          />
          <button className="btn primary" type="button" disabled={importing} onClick={() => void importContract()}>
            {importing ? '比较中…' : '导入并比较'}
          </button>
          {importMessage && <span className="success-text">{importMessage}</span>}
        </div>
      </div>

      <div className="panel">
        <div className="panel-head">
          <h3 className="panel-title">契约比较批次</h3>
          <div className="form-row" style={{ marginTop: 0 }}>
            <input
              className="inline-input"
              placeholder="按接口编号过滤，如 SCHE-0002"
              value={batchFilter}
              onChange={(event) => setBatchFilter(event.target.value)}
            />
            <button className="btn ghost" type="button" onClick={() => void reloadBatches(batchFilter)}>刷新批次</button>
          </div>
        </div>
        {batches.length === 0 ? (
          <p className="panel-hint">该接口暂无契约批次，先在上方导入第一版契约生成快照。</p>
        ) : (
          batches.map((batch) => (
            <article key={batch.id} className="panel" style={{ marginBottom: 10 }}>
              <div className="panel-head">
                <div>
                  <strong>{batch.批次编号}</strong>
                  <span style={{ marginLeft: 8 }}>{batch.接口编号} · {batch.契约版本}</span>
                  {batch.复用 && <span className="badge neutral" style={{ marginLeft: 8 }}>指纹复用</span>}
                </div>
                <span className={verdictClass(batch.兼容结论)}>{batch.兼容结论}</span>
              </div>
              <div className="batch-meta">
                <span>来源：{batch.文件名}</span>
                <span>导入时间：{batch.导入时间}</span>
                <span>变化字段：{batch.变化字段数} 个</span>
                <span className="fingerprint">指纹：{batch.指纹.slice(0, 16)}…</span>
              </div>
              {batch.说明 && <p className="panel-hint">{batch.说明}</p>}
              {batch.提示 && <p className="panel-hint">{batch.提示}</p>}
              {batch.变化字段数 > 0 && (
                <>
                  <button
                    className="link"
                    type="button"
                    onClick={() => setExpanded(expanded === batch.id ? null : batch.id)}
                  >
                    {expanded === batch.id ? '收起变化字段' : `查看 ${batch.变化字段数} 个变化字段`}
                  </button>
                  {expanded === batch.id && (
                    <table className="change-table">
                      <thead>
                        <tr>
                          <th>方向</th>
                          <th>变更种类</th>
                          <th>字段</th>
                          <th>旧类型 → 新类型</th>
                          <th>位置变化</th>
                          <th>结论</th>
                          <th>判定理由</th>
                        </tr>
                      </thead>
                      <tbody>
                        {batch.变更明细.map((change, index) => (
                          <tr key={`${batch.id}-${index}`}>
                            <td>{change.方向}</td>
                            <td><span className="kind-tag">{change.变更种类}</span></td>
                            <td>{change.字段名称}{change.必填 ? '（必填）' : ''}</td>
                            <td>{change.旧类型 || '缺失'} → {change.新类型 || '缺失'}</td>
                            <td>
                              {change.旧位置 === change.新位置
                                ? '—'
                                : `${change.旧位置 ?? '—'} → ${change.新位置 ?? '—'}`}
                            </td>
                            <td><span className={verdictClass(change.兼容结论)}>{change.兼容结论}</span></td>
                            <td>{change.判定理由}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </>
              )}
            </article>
          ))
        )}
      </div>

      <div className="stat-row">
        {stats.map((item) => (
          <article key={item.label} className="stat-card">
            <span className="stat-label">{item.label}</span>
            <strong className="stat-value">{item.value}</strong>
          </article>
        ))}
      </div>

      <form className="filter-bar" onSubmit={(event) => { event.preventDefault(); void reload() }}>
        {filterFields.map((field) => (
          <label key={field} className="filter-item">
            <span>{field}</span>
            <input
              value={filters[field] ?? ''}
              placeholder={`按${field}检索`}
              onChange={(event) => setFilters((prev) => ({ ...prev, [field]: event.target.value }))}
            />
          </label>
        ))}
        <button className="btn" type="submit">查询</button>
        <button className="btn ghost" type="button" onClick={() => setFilters({})}>重置条件</button>
      </form>

      <table className="data-table">
        <thead>
          <tr>
            {columns.map((column) => <th key={column}>{column}</th>)}
            <th>可执行动作</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={String(row.id)}>
              {columns.map((column) => <td key={column}>{row[column] ?? '—'}</td>)}
              <td className="row-actions">
                {actions.map((action) => (
                  <button key={action} className="link" type="button" onClick={() => void runAction(action, row)}>
                    {action}
                  </button>
                ))}
              </td>
            </tr>
          ))}
          {rows.length === 0 && (
            <tr>
              <td className="empty-state" colSpan={columns.length + 1}>暂无数据接口契约数据，可先登记接口定义</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条数据接口契约记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
