import type { ReactNode } from 'react'
import { Link, useLocation } from 'react-router-dom'
import {
  ApartmentOutlined,
  ClusterOutlined,
  FileSearchOutlined,
  HomeOutlined,
  RiseOutlined,
  TeamOutlined,
  UserOutlined,
  BulbOutlined,
  BulbFilled,
  RocketOutlined,
  SafetyCertificateOutlined,
  SettingOutlined,
} from '@ant-design/icons'
import { useTheme } from '../context/ThemeContext'

interface NavItem {
  path: string
  label: string
  icon: ReactNode
}

const NAV_ITEMS: NavItem[] = [
  { path: '/', label: '总览', icon: <HomeOutlined /> },
  { path: '/graph', label: '星图', icon: <ClusterOutlined /> },
  { path: '/applicant', label: '简历评估', icon: <FileSearchOutlined /> },
  { path: '/hr', label: 'HR 工作台', icon: <TeamOutlined /> },
  { path: '/evolution', label: '动态演化', icon: <RiseOutlined /> },
  { path: '/review', label: '审核中心', icon: <SafetyCertificateOutlined /> },
  { path: '/admin', label: '管理员', icon: <SettingOutlined /> },
]

export default function SpaceNav() {
  const location = useLocation()
  const { mode: theme, toggle: toggleTheme } = useTheme()

  // 根据主题显示不同图标
  const getThemeIcon = () => {
    switch (theme) {
      case 'light':
        return <BulbFilled />
      case 'apollo':
        return <RocketOutlined />
      default:
        return <BulbOutlined />
    }
  }

  const getThemeTitle = () => {
    switch (theme) {
      case 'light':
        return '切换到 Apollo 主题'
      case 'apollo':
        return '切换到深色主题'
      default:
        return '切换到浅色主题'
    }
  }

  return (
    <nav className="space-nav">
      <div className="space-nav__inner">
        <Link to="/" className="space-brand" aria-label="动态岗位能力图谱首页">
          <div className="space-brand__mark">
            <ApartmentOutlined />
          </div>
          <div className="space-brand__copy">
            <div className="space-brand__name">
              岗位能力图谱
            </div>
            <div className="space-brand__meta">
              SKILL GRAPH / LIVE
            </div>
          </div>
        </Link>

        <div className="space-nav__links" aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const isActive = location.pathname === item.path
            return (
              <Link
                key={item.path}
                to={item.path}
                className={`nav-item${isActive ? ' active' : ''}`}
              >
                <span className="nav-item__icon">{item.icon}</span>
                <span>{item.label}</span>
              </Link>
            )
          })}
        </div>

        <div className="space-nav__right">
          <div className="space-nav__status" title="数据管道运行状态">
            <span className="space-nav__pulse" />
            <span>实时更新</span>
          </div>

          <div className="space-nav__metric">
            <strong>12,847</strong>
            <span>岗位</span>
          </div>
          <div className="space-nav__metric">
            <strong>98,321</strong>
            <span>技能</span>
          </div>

          <button
            onClick={toggleTheme}
            className="space-nav__theme-toggle"
            title={getThemeTitle()}
            aria-label="切换主题"
          >
            {getThemeIcon()}
          </button>

          <div className="space-nav__avatar" title="当前用户">
            <UserOutlined />
          </div>
        </div>
      </div>
    </nav>
  )
}
