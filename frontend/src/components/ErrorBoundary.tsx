import { Component, type ErrorInfo, type ReactNode } from 'react'

type Props = { children: ReactNode }
type State = { error: Error | null }

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('Frontend render failed', error, info.componentStack)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="page-shell min-h-screen pt-24 px-6">
        <section className="archive-panel glass mx-auto max-w-xl p-8 text-center">
          <h1 className="text-xl font-semibold text-[var(--text)]">页面加载失败</h1>
          <p className="mt-3 text-sm text-[var(--text-dim)]">请刷新页面重试；问题仍存在时联系系统管理员。</p>
          <button className="btn btn-primary mt-6" type="button" onClick={() => window.location.reload()}>
            重新加载
          </button>
        </section>
      </main>
    )
  }
}
