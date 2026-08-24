import type { Star } from '../types/graph'

type RoleMatchInput = {
  jobRoleId?: string | null
  roleId?: string | null
  canonicalName?: string | null
  domainName?: string | null
  definitionPayload?: Record<string, unknown> | null
}

const GRAPH_ID_KEYS = ['graph_star_id', 'graphNodeId', 'graph_node_id', 'star_id', 'jd_graph_star_id']
const ROLE_NAME_KEYS = ['role_name', 'canonical_name', 'job_title', 'title', 'name']

export function normalizeGraphRoleName(value?: string | null) {
  return (value ?? '')
    .normalize('NFKC')
    .toLowerCase()
    .replace(/[（(][^）)]*[）)]/g, '')
    .replace(/[\s·/|_\-—–:：,，.。]+/g, '')
    .trim()
}

function payloadString(payload: Record<string, unknown> | null | undefined, key: string) {
  const value = payload?.[key]
  return typeof value === 'string' && value.trim() ? value : null
}

function uniqueValues(values: Array<string | null | undefined>) {
  return Array.from(new Set(values.filter((value): value is string => Boolean(value && value.trim()))))
}

function starAliases(star: Star) {
  return uniqueValues([
    star.id,
    star.label,
    star.name,
    ...(star.sampleJobs?.slice(0, 6).map((job) => job.jobName) ?? []),
  ]).map(normalizeGraphRoleName)
}

export function findGraphStarForRole(stars: Star[], role: RoleMatchInput) {
  const payload = role.definitionPayload ?? null
  const roleIds = uniqueValues([
    role.jobRoleId,
    role.roleId,
    ...GRAPH_ID_KEYS.map((key) => payloadString(payload, key)),
  ])

  const direct = stars.find((star) => roleIds.includes(star.id))
  if (direct) return direct

  const targetNames = uniqueValues([
    role.canonicalName,
    ...ROLE_NAME_KEYS.map((key) => payloadString(payload, key)),
  ])
    .map(normalizeGraphRoleName)
    .filter(Boolean)

  if (targetNames.length === 0) return null

  const exact = stars.find((star) => starAliases(star).some((alias) => targetNames.includes(alias)))
  if (exact) return exact

  const normalizedDomain = normalizeGraphRoleName(role.domainName)
  let best: { star: Star; score: number } | null = null

  for (const star of stars) {
    const aliases = starAliases(star)
    let score = 0

    for (const alias of aliases) {
      for (const target of targetNames) {
        const shorter = Math.min(alias.length, target.length)
        const longer = Math.max(alias.length, target.length)
        if (shorter < 3 || longer === 0) continue
        if (alias.includes(target) || target.includes(alias)) {
          score = Math.max(score, 0.62 + shorter / longer * 0.28)
        }
      }
    }

    if (normalizedDomain && normalizeGraphRoleName(star.domain) === normalizedDomain) {
      score += 0.08
    }

    if (!best || score > best.score) {
      best = { star, score }
    }
  }

  return best && best.score >= 0.72 ? best.star : null
}
