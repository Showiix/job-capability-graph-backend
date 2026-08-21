import { HomeOutlined } from '@ant-design/icons'
import { Link } from 'react-router-dom'

export default function ArchiveReturnHome() {
  return (
    <Link className="archive-return-home" to="/" aria-label="返回月面档案首页">
      <span className="archive-return-home__lens">
        <span className="archive-return-home__outline" />
        <span className="archive-return-home__scan" />
        <span className="archive-return-home__foreground">
          <HomeOutlined />
        </span>
      </span>
      <span className="archive-return-home__copy">
        <span>RETURN</span>
        <strong>ARCHIVE</strong>
      </span>
    </Link>
  )
}
