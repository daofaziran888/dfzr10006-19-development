import { useCallback, useEffect, useMemo, useState } from 'react'

import { request } from '@/api/client'

const ENDPOINT = '/api/whitelist'

type Verdict = '兼容' | '不兼容' | '不可判定'

interface CompatibilityChange {
  方向: string
  变更种类: string
  字段名称: string
  兼容结论: Verdict
  判定理由: string
}

interface CompatibilityBatch {
  批次编号: string
  接口编号: string
  契约版本: string
  导入时间: string
  兼容结论: Verdict
  变化字段数: number
  变更明细: CompatibilityChange[]
}

function verdictClass(verdict: string): string {
  if (verdict === '兼容') return 'badge compatible'
  if (verdict === '不兼容') return 'badge incompatible'
  if (verdict === '不可判定') return 'badge undecidable'
  return 'badge neutral'
}

const columns = [
  "登记编号",
  "应用名称",
  "调用标识",
  "日配额上限",
  "优先级",
  "生效日期",
  "失效日期",
  "登记状态"
]
const actions = [
  "启用登记",
  "冻结来源",
  "注销来源"
]
const statuses = [
  "草稿",
  "已登记",
  "已冻结",
  "已注销"
]
const stats = [
  {
    "label": "来源登记总数",
    "value": 0
  },
  {
    "label": "已登记来源",
    "value": 0
  },
  {
    "label": "已冻结来源",
    "value": 0
  }
]

type Row = Record<string, string | number | null>

export default function WhitelistView() {
  const [rows, setRows] = useState<Row[]>([])
  const [total, setTotal] = useState(0)
  const [errorMessage, setErrorMessage] = useState('')
  const [filters, setFilters] = useState<Record<string, string>>({})
  const filterFields = useMemo(() => columns.slice(0, 3), [])

  const [interfaceCode, setInterfaceCode] = useState('SCHE-0002')
  const [compatLoading, setCompatLoading] = useState(false)
  const [compatBatch, setCompatBatch] = useState<CompatibilityBatch | null>(null)
  const [compatEmpty, setCompatEmpty] = useState('')

  async function queryCompatibility() {
    setErrorMessage('')
    setCompatEmpty('')
    setCompatBatch(null)
    const code = interfaceCode.trim()
    if (!code) {
      setErrorMessage('请先输入接口编号')
      return
    }
    setCompatLoading(true)
    try {
      const response = await request(`${ENDPOINT}/compatibility?interface_code=${encodeURIComponent(code)}`)
      if (!response.ok) {
        throw new Error('兼容性结论读取失败')
      }
      const payload = await response.json()
      if (payload.有结论) {
        setCompatBatch(payload.batch)
      } else {
        setCompatEmpty(payload.message ?? '该接口暂无兼容性结论')
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '兼容性结论读取失败')
    } finally {
      setCompatLoading(false)
    }
  }

  const reload = useCallback(async () => {
    setErrorMessage('')
    const query = new URLSearchParams(filters).toString()
    try {
      const response = await request(`${ENDPOINT}?${query}`)
      if (!response.ok) {
        throw new Error('来源登记列表读取失败')
      }
      const payload = await response.json()
      setRows(payload.items ?? [])
      setTotal(payload.total ?? 0)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '调用来源管理列表读取失败')
    }
  }, [filters])

  useEffect(() => {
    void reload()
  }, [reload])

  async function runAction(action: string, row: Row) {
    setErrorMessage('')
    try {
      const response = await request(`${ENDPOINT}/${row.id}/actions`, {
        method: 'POST',
        body: JSON.stringify({ action }),
      })
      if (!response.ok) {
        throw new Error('调用来源管理动作未生效，请稍后重试')
      }
      await reload()
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : '调用来源管理操作失败')
    }
  }

  return (
    <section className="page" data-module="whitelist">
      <header className="page-head">
        <div>
          <h2>调用来源管理管理</h2>
          <p className="page-desc">维护调用来源的标识登记、配额分配与有效期管理，为调用来源管理提供可审计的数据工程流程。</p>
        </div>
        <div className="page-actions">
          <button className="btn primary" type="button" onClick={() => setErrorMessage('来源登记登记入口尚未接入审批流')}>
            登记来源登记
          </button>
          <button className="btn" type="button" onClick={() => window.open(`${ENDPOINT}/export`, '_blank')}>
            导出调用来源管理清单
          </button>
        </div>
      </header>

      <div className="panel">
        <div className="panel-head">
          <h3 className="panel-title">按接口编号读取契约兼容性结论</h3>
        </div>
        <p className="panel-hint">
          结论与「数据接口契约」模块同源：这里不重新比较，只读取该接口最新契约批次的兼容性判断，用于评估调用来源是否会因契约调整而失配。
        </p>
        <div className="form-row">
          <input
            className="inline-input"
            placeholder="接口编号，如 SCHE-0002"
            value={interfaceCode}
            onChange={(event) => setInterfaceCode(event.target.value)}
          />
          <button className="btn primary" type="button" disabled={compatLoading} onClick={() => void queryCompatibility()}>
            {compatLoading ? '读取中…' : '读取兼容性结论'}
          </button>
        </div>
        {compatBatch && (
          <div style={{ marginTop: 12 }}>
            <div className="panel-head">
              <div>
                <strong>{compatBatch.批次编号}</strong>
                <span style={{ marginLeft: 8 }}>{compatBatch.接口编号} · 契约版本 {compatBatch.契约版本}</span>
              </div>
              <span className={verdictClass(compatBatch.兼容结论)}>{compatBatch.兼容结论}</span>
            </div>
            <div className="batch-meta">
              <span>导入时间：{compatBatch.导入时间}</span>
              <span>变化字段：{compatBatch.变化字段数} 个</span>
            </div>
            {compatBatch.变化字段数 > 0 && (
              <table className="change-table">
                <thead>
                  <tr>
                    <th>方向</th>
                    <th>变更种类</th>
                    <th>字段</th>
                    <th>结论</th>
                    <th>判定理由</th>
                  </tr>
                </thead>
                <tbody>
                  {compatBatch.变更明细.map((change, index) => (
                    <tr key={index}>
                      <td>{change.方向}</td>
                      <td><span className="kind-tag">{change.变更种类}</span></td>
                      <td>{change.字段名称}</td>
                      <td><span className={verdictClass(change.兼容结论)}>{change.兼容结论}</span></td>
                      <td>{change.判定理由}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>
        )}
        {compatEmpty && <p className="panel-hint" style={{ marginBottom: 0 }}>{compatEmpty}</p>}
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
              <td className="empty-state" colSpan={columns.length + 1}>暂无调用来源管理数据，可先登记来源登记</td>
            </tr>
          )}
        </tbody>
      </table>

      <footer className="page-foot">
        <span>共 {total} 条调用来源管理记录</span>
        {errorMessage && <span className="error-text">{errorMessage}</span>}
      </footer>
    </section>
  )
}
