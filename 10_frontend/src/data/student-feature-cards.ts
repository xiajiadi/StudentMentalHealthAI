export const studentFeatureCards = [
  {
    tag: '自我探索',
    title: '从一次测评开始',
    description: '一题一答之间，记下此刻的学习、生活与感受。',
    to: '/student/assessments',
    image: '/assets/psynova/academy-feature-self-exploration.jpeg',
    imageAlt: '蓝色、青色与粉色交织的流动渐变',
  },
  {
    tag: '测评反馈',
    title: '换个角度看自己',
    description: '读一读已发布的反馈，从不同角度理解自己的近况。',
    to: '/student/feedback',
    image: '/assets/psynova/academy-feature-assessment-feedback.png',
    imageAlt: '绿色、青色与浅黄色交织的柔和渐变',
  },
  {
    tag: '教育支持',
    title: '有困惑，就聊聊',
    description: '学习、生活与人际相处的难题，都可以从一次对话说起。',
    to: '/student/support',
    image: '/assets/psynova/academy-feature-education-support.png',
    imageAlt: '橙色、紫色与粉色交织的柔和渐变',
  },
  {
    tag: '成长记录',
    title: '回望来时路',
    description: '翻看测评与支持记录，看看自己在不同阶段的变化。',
    to: '/student/history',
    image: '/assets/psynova/academy-feature-growth-record.png',
    imageAlt: '粉色、蓝色、紫色与淡金色交织的渐变',
  },
] as const

export const studentPageArt = {
  assessments: studentFeatureCards[0].image,
  feedback: studentFeatureCards[1].image,
  educationSupport: studentFeatureCards[2].image,
  history: studentFeatureCards[3].image,
} as const

export const studentPageTitles = {
  assessments: studentFeatureCards[0].tag,
  feedback: studentFeatureCards[1].tag,
  educationSupport: studentFeatureCards[2].tag,
  history: studentFeatureCards[3].tag,
} as const

export const studentPageBannerCopy = {
  assessments: {
    eyebrow: 'ASSESSMENT CENTER',
    subtitle: '探索潜能与阶段性成长反馈',
  },
  feedback: {
    eyebrow: 'FEEDBACK & INSIGHTS',
    subtitle: '多维数据分析与个性化成长建议',
  },
  educationSupport: {
    eyebrow: 'EDUCATION SUPPORT',
    subtitle: '专属学习资源与科学指导方案',
  },
  history: {
    eyebrow: 'ACTIVITY ARCHIVE',
    subtitle: '全面回顾历史测评轨迹与成长足迹',
  },
} as const
