import articles from '../../../09_backend/src/smhai_backend/domains/student_education_articles.json'

export const studentEducationArticles = articles

const byTopic = new Map(articles.map((article) => [article.id, article]))

export function articlesForTopics(topics: string[]) {
  return topics.flatMap((topic) => byTopic.get(topic) || [])
}
