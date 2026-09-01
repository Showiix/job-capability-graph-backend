import { useEffect, useState } from 'react'
import { Alert, Button, Input } from 'antd'
import { useAuth } from '../context/AuthContext'
import { decideReviewProposal, listReviewProposals, type ReviewProposal } from '../services/adminApi'

export default function ReviewCenterPage() {
  const { user, login } = useAuth(); const [username, setUsername] = useState(''); const [password, setPassword] = useState(''); const [items, setItems] = useState<ReviewProposal[]>([]); const [error, setError] = useState('')
  const load = () => listReviewProposals().then(setItems).catch((e) => setError(e.apiMessage ?? e.message))
  useEffect(() => { if (user && user.role !== 'applicant') void load() }, [user])
  if (!user || user.role === 'applicant') return <Login title="审核中心" username={username} password={password} setUsername={setUsername} setPassword={setPassword} onLogin={() => login(username, password).then(load).catch((e) => setError(e.message))} error={error} />
  return <main className="page-shell min-h-screen pt-20 px-8"><div className="max-w-5xl mx-auto"><h1 className="page-shell__title">审核中心</h1><p className="text-[var(--text-dim)] mb-6">真实待审核岗位提案</p>{error && <p className="text-red-400">{error}</p>}{items.map((item) => <article key={item.id} className="archive-panel glass p-5 mb-3"><strong>{item.proposed_payload?.role_name ?? item.change_type}</strong><span className="ml-4 text-xs">{item.review_status}</span><pre className="text-xs mt-3">{JSON.stringify(item.proposed_payload, null, 2)}</pre><div className="flex gap-2"><button className="btn btn-primary" onClick={() => decideReviewProposal(item.id, 'approve', '审核通过').then(load)}>通过</button><button className="btn btn-ghost" onClick={() => decideReviewProposal(item.id, 'revise', '需要补充岗位定义', item.proposed_payload).then(load)}>要求修改</button><button className="btn btn-ghost" onClick={() => decideReviewProposal(item.id, 'reject', '审核驳回').then(load)}>驳回</button></div></article>)}</div></main>
}

function Login({ title, username, password, setUsername, setPassword, onLogin, error }: any) {
  return <main className="page-shell min-h-screen pt-20 px-8"><div className="archive-panel glass p-8 max-w-md mx-auto"><h1 className="text-2xl mb-5">{title}登录</h1><div className="flex flex-col gap-4"><Input size="large" placeholder="用户名" value={username} onChange={(e) => setUsername(e.target.value)} aria-label="用户名" /><Input.Password size="large" placeholder="密码" value={password} onChange={(e) => setPassword(e.target.value)} aria-label="密码" /><Button type="primary" size="large" onClick={onLogin}>登录</Button>{error && <Alert type="error" showIcon message={error} />}</div></div></main>
}
