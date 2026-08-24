import type { Star, Planet, GraphData } from '../types/graph'

// Mock 数据 - 后续会替换为 API 调用
export const MOCK_GRAPH_DATA: GraphData = {
  stars: [
    {
      id: 'job_ml',
      label: '机器学习工程师',
      domain: '数据/AI',
      color: '#fff3ea',
      position: [-5, 0, -2],
      size: 1.2,
      requiredSkills: ['Python', 'PyTorch', '特征工程', 'Scikit-learn'],
      bonusSkills: ['Kubernetes', 'MLflow', 'CUDA'],
      sources: 142,
    },
    {
      id: 'job_nlp',
      label: 'NLP 算法工程师',
      domain: '大语言模型',
      color: '#e4b592',
      position: [5, 2, -1],
      size: 1.3,
      requiredSkills: ['Transformer', 'BERT', 'Python', 'HuggingFace'],
      bonusSkills: ['LangChain', 'RAG', 'vLLM'],
      sources: 98,
    },
    {
      id: 'job_data',
      label: '数据分析师',
      domain: '数据分析',
      color: '#dad0c8',
      position: [0, -3, 2],
      size: 1.0,
      requiredSkills: ['SQL', 'Python', 'Tableau', '统计学'],
      bonusSkills: ['Power BI', 'R语言'],
      sources: 203,
    },
    {
      id: 'job_pm',
      label: 'AI 产品经理',
      domain: '产品/设计',
      color: '#b9aea4',
      position: [4, -2, 3],
      size: 1.0,
      requiredSkills: ['需求分析', '数据决策', 'Axure', 'Prompt工程'],
      bonusSkills: ['A/B测试', 'LLM应用'],
      sources: 165,
    },
    {
      id: 'job_cv',
      label: 'CV 工程师',
      domain: '计算机视觉',
      color: '#ee1212',
      position: [-4, -1, 3],
      size: 0.95,
      requiredSkills: ['PyTorch', 'OpenCV', 'YOLO', '图像处理'],
      bonusSkills: ['TensorRT', 'ONNX'],
      sources: 87,
    },
  ],
  planets: [],
}

// 构建行星数据
function buildPlanets(stars: Star[]): Planet[] {
  const planets: Planet[] = []

  const typeMap: Record<string, 'core' | 'foundation' | 'frontier'> = {
    Python: 'foundation',
    PyTorch: 'core',
    '特征工程': 'core',
    'Scikit-learn': 'foundation',
    Kubernetes: 'core',
    MLflow: 'core',
    CUDA: 'frontier',
    Transformer: 'frontier',
    BERT: 'frontier',
    HuggingFace: 'core',
    LangChain: 'frontier',
    RAG: 'frontier',
    vLLM: 'frontier',
    SQL: 'foundation',
    Tableau: 'core',
    '统计学': 'foundation',
    'Power BI': 'core',
    'R语言': 'foundation',
    '需求分析': 'foundation',
    '数据决策': 'core',
    Axure: 'foundation',
    'Prompt工程': 'frontier',
    'A/B测试': 'core',
    'LLM应用': 'frontier',
    OpenCV: 'core',
    YOLO: 'core',
    '图像处理': 'foundation',
    TensorRT: 'frontier',
    ONNX: 'core',
  }

  const typeColor: Record<string, string> = {
    core: '#ee1212',
    foundation: '#dad0c8',
    frontier: '#e4b592',
  }

  stars.forEach((star) => {
    // Required skills (inner orbits)
    star.requiredSkills.forEach((label, i) => {
      const type = typeMap[label] ?? 'core'
      planets.push({
        id: `${star.id}_${label}`,
        starId: star.id,
        label,
        type,
        isRequired: true,
        orbitRadius: 2 + i * 0.6,
        orbitTilt: Math.PI / 8,
        orbitPhase: (i / star.requiredSkills.length) * Math.PI * 2,
        orbitSpeed: 0.3 - i * 0.05,
        size: 0.25,
        confidence: 85 + Math.floor(Math.random() * 14),
        color: typeColor[type],
      })
    })

    // Bonus skills (outer orbits)
    star.bonusSkills.forEach((label, i) => {
      const type = typeMap[label] ?? 'frontier'
      planets.push({
        id: `${star.id}_${label}`,
        starId: star.id,
        label,
        type,
        isRequired: false,
        orbitRadius: 4 + i * 0.7,
        orbitTilt: Math.PI / 10,
        orbitPhase: (i / star.bonusSkills.length) * Math.PI * 2 + Math.PI,
        orbitSpeed: 0.15 - i * 0.02,
        size: 0.2,
        confidence: 70 + Math.floor(Math.random() * 18),
        color: typeColor[type],
      })
    })
  })

  return planets
}

// 初始化完整的图谱数据
MOCK_GRAPH_DATA.planets = buildPlanets(MOCK_GRAPH_DATA.stars)

export default MOCK_GRAPH_DATA
