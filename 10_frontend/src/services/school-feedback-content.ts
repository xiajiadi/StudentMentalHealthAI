const nextStepsSeparator = '\n\n【老师建议的下一步】\n'

export function schoolFeedbackContent(body: string, nextSteps: string): string {
  const steps = nextSteps.trim()
  return steps ? `${body.trimEnd()}${nextStepsSeparator}${steps}` : body
}

export function readSchoolFeedbackContent(body: string): { body: string; nextSteps: string } {
  const split = body.indexOf(nextStepsSeparator)
  if (split < 1) return { body, nextSteps: '' }
  const nextSteps = body.slice(split + nextStepsSeparator.length).trim()
  return nextSteps ? { body: body.slice(0, split), nextSteps } : { body, nextSteps: '' }
}
