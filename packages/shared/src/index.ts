/**
 * Shared contract between the API and the web app.
 *
 * `api.d.ts` is generated from the FastAPI OpenAPI schema by `npm run generate`
 * and is checked for drift in CI (the `contract` job). Never edit it by hand.
 *
 * Hand-written types below are limited to things the schema cannot express.
 */

// Re-exported so consumers import from one place. `components["schemas"]["X"]`
// is the generated shape of every response the API can return.
export type { components, operations, paths } from "./api";

/** Error envelope returned by every non-2xx API response. */
export interface ApiErrorBody {
  error: {
    /** Stable, machine-readable. Branch on this, never on `message`. */
    code: string;
    /** Human-readable. May change without notice. */
    message: string;
    details?: Record<string, unknown> | null;
    request_id: string;
  };
}

/** Cursor-paginated list envelope. */
export interface Paginated<T> {
  data: T[];
  pagination: {
    next_cursor: string | null;
    has_more: boolean;
    limit: number;
  };
}

export const ID_PREFIXES = {
  organization: "org_",
  user: "usr_",
  membership: "mem_",
  apiKey: "ak_",
  subject: "sub_",
  faceProfile: "fp_",
  faceTemplate: "ft_",
  enrollment: "enr_",
  verificationSession: "vs_",
  request: "req_",
} as const;

export type IdPrefix = (typeof ID_PREFIXES)[keyof typeof ID_PREFIXES];
