import articles from '@student-education-articles'

export const studentEducationArticles = articles

const byTopic = new Map(articles.map((article) => [article.id, article]))

export function articlesForTopics(topics: string[]) {
  return topics.flatMap((topic) => byTopic.get(topic) || [])
}
