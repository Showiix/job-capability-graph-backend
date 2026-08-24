# 多源异构岗位能力动态图谱系统 - 前端（整理版）

基于 React 19 + TypeScript + Vite 8 + Tailwind CSS 4.0 构建的空间主题知识图谱可视化系统。

## 🚀 技术栈

- **框架**: React 19 + TypeScript
- **构建工具**: Vite 8
- **样式**: Tailwind CSS 4.0
- **3D可视化**: Three.js + React Three Fiber + Drei
- **图表**: Recharts
- **路由**: React Router v6
- **UI组件**: Ant Design

## 📁 项目结构

```
src/
├── components/          # 组件
│   ├── SpaceNav.tsx    # 顶部导航栏（玻璃态）
│   ├── Star.tsx        # 恒星组件（岗位节点）
│   ├── Planet.tsx      # 行星组件（技能节点）
│   └── GraphScene3D.tsx # 3D场景容器
├── pages/              # 页面
│   ├── SpaceHomePage.tsx        # 首页（轨道动画）
│   ├── SpaceGraphPage.tsx       # 3D知识图谱
│   ├── ApplicantFlowPage.tsx    # 应聘者流程（4步）
│   ├── HRWorkspacePage.tsx      # HR工作台（4步）
│   └── EmergingJobsPage.tsx     # 新兴岗位发现
├── services/           # API服务层
│   ├── graphApi.ts     # 知识图谱API
│   ├── api.ts          # 通用API
│   └── request.ts      # HTTP请求工具
├── types/              # TypeScript类型定义
│   ├── graph.ts        # 图谱数据类型
│   └── api.ts          # API响应类型
├── data/               # 数据
│   └── mockGraphData.ts # Mock数据
├── context/            # React Context
│   ├── ThemeContext.tsx # 主题切换
│   └── AuthContext.tsx  # 认证管理
├── routes/             # 路由配置
│   └── index.tsx
├── styles/             # 样式文件
│   └── space-theme.css  # 空间主题样式
├── utils/              # 工具函数
├── main.tsx            # 应用入口
├── App.tsx             # 主应用组件
└── index.css           # 全局样式
```

## 🛠️ 开发

```bash
# 安装依赖
npm install

# 启动开发服务器
npm run dev

# 构建生产版本
npm run build

# 预览生产构建
npm run preview
```

## 📱 路由

- `/` - 首页
- `/graph` - 3D知识图谱
- `/applicant` - 应聘者流程
- `/hr` - HR工作台
- `/emerging` - 新兴岗位

## 🎨 设计特点

- **空间主题**: 恒星-行星轨道隐喻岗位-技能关系
- **玻璃态设计**: 毛玻璃效果 + 渐变边框
- **3D可视化**: Three.js实现的轨道运动系统
- **响应式布局**: 适配桌面端

## 📝 API配置

API请求会自动代理到 `http://localhost:8000/api/v1`（参见 vite.config.ts）

## 🔗 相关文档

- [Vite文档](https://vitejs.dev/)
- [React文档](https://react.dev/)
- [Tailwind CSS文档](https://tailwindcss.com/)
- [Three.js文档](https://threejs.org/)
