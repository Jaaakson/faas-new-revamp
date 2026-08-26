/**
 * Query key factory.
 *
 * **Every console key begins with the organization id.** That single convention
 * is what makes org switching safe: invalidating `["org", oldId]` removes
 * exactly that tenant's cached data and nothing else, and two organizations can
 * never collide on a shared key. A key like `["members"]` would show the
 * previous tenant's member list for a frame after switching — which for a
 * multi-tenant product is a data-leak-shaped bug even though the server did
 * everything right.
 */

export const queryKeys = {
  org: (organizationId: string) => ["org", organizationId] as const,

  overview: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "overview", days] as const,
  timeseries: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "timeseries", days] as const,
  outcomes: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "outcomes", days] as const,
  failureReasons: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "failure-reasons", days] as const,
  latency: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "latency", days] as const,
  hourly: (organizationId: string, days: number) =>
    ["org", organizationId, "analytics", "hourly", days] as const,

  usage: (organizationId: string) => ["org", organizationId, "usage"] as const,

  verifications: (organizationId: string, filters: Record<string, unknown>) =>
    ["org", organizationId, "verifications", filters] as const,
  verification: (organizationId: string, verificationId: string) =>
    ["org", organizationId, "verifications", "detail", verificationId] as const,
  threshold: (organizationId: string) => ["org", organizationId, "threshold"] as const,
  webhooks: (organizationId: string) => ["org", organizationId, "webhooks"] as const,
  webhookDeliveries: (organizationId: string, endpointId: string) =>
    ["org", organizationId, "webhooks", endpointId, "deliveries"] as const,
  subjects: (organizationId: string, filters: Record<string, unknown>) =>
    ["org", organizationId, "subjects", filters] as const,
  subject: (organizationId: string, subjectId: string) =>
    ["org", organizationId, "subjects", "detail", subjectId] as const,
  enrollments: (organizationId: string, filters: Record<string, unknown>) =>
    ["org", organizationId, "enrollments", filters] as const,

  auditLog: (organizationId: string, filters: Record<string, unknown>) =>
    ["org", organizationId, "logs", "audit", filters] as const,
  authLog: (organizationId: string, filters: Record<string, unknown>) =>
    ["org", organizationId, "logs", "auth", filters] as const,

  apiKeys: (organizationId: string) => ["org", organizationId, "api-keys"] as const,
  members: (organizationId: string) => ["org", organizationId, "members"] as const,
  invitations: (organizationId: string) => ["org", organizationId, "invitations"] as const,
  settings: (organizationId: string) => ["org", organizationId, "settings"] as const,
  organization: (organizationId: string) => ["org", organizationId, "organization"] as const,

  /** Not org-scoped: identity spans organizations. */
  me: () => ["me"] as const,
} as const;
