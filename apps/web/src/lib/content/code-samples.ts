/**
 * Code samples shown across the marketing site and docs.
 *
 * Kept in one module because the same request appears on the landing page, the
 * features page, and the quickstart. Three hand-maintained copies of a request
 * body drift the first time the API changes — and a wrong sample on a landing
 * page is worse than no sample.
 *
 * Every field here matches docs/07-api-design.md §3.
 */

export const VERIFY_CURL = `curl https://api.fvas.io/v1/verifications \\
  -H "Authorization: Bearer fvas_live_9f2c8a…" \\
  -H "Content-Type: application/json" \\
  -d '{
    "subject_id": "sub_01HQZX8K4M2N7P",
    "image": "<base64 jpeg>"
  }'`;

export const VERIFY_NODE = `import { Fvas } from "@fvas/node";

const fvas = new Fvas(process.env.FVAS_API_KEY);

const result = await fvas.verifications.create({
  subjectId: "sub_01HQZX8K4M2N7P",
  image: frameBuffer,
});

if (result.decision === "verified") {
  await approveTransfer(transferId);
}`;

export const VERIFY_PYTHON = `from fvas import Fvas

fvas = Fvas(api_key=os.environ["FVAS_API_KEY"])

result = fvas.verifications.create(
    subject_id="sub_01HQZX8K4M2N7P",
    image=frame_bytes,
)

if result.decision == "verified":
    approve_transfer(transfer_id)`;

export const VERIFY_GO = `req, _ := json.Marshal(map[string]string{
    "subject_id": "sub_01HQZX8K4M2N7P",
    "image":      base64.StdEncoding.EncodeToString(frame),
})

r, _ := http.NewRequest("POST", "https://api.fvas.io/v1/verifications", bytes.NewReader(req))
r.Header.Set("Authorization", "Bearer "+os.Getenv("FVAS_API_KEY"))
r.Header.Set("Content-Type", "application/json")

resp, err := http.DefaultClient.Do(r)`;

export const VERIFY_RESPONSE = `{
  "id": "vs_01HQZXA4B6C8",
  "decision": "verified",
  "subject_id": "sub_01HQZX8K4M2N7P",
  "similarity": 0.8121,
  "threshold": 0.38,
  "confidence": "high",
  "templates_compared": 3,
  "timing": { "total_ms": 284, "detect_ms": 62, "embed_ms": 148, "match_ms": 31 },
  "created_at": "2026-07-30T07:24:11Z"
}`;

export const CREATE_SUBJECT = `curl https://api.fvas.io/v1/subjects \\
  -H "Authorization: Bearer fvas_test_…" \\
  -d '{
    "external_id": "user_84213",
    "consent_reference": "consent_2026_07_30_84213"
  }'`;

export const ENROLL = `curl https://api.fvas.io/v1/enrollments \\
  -H "Authorization: Bearer fvas_test_…" \\
  -d '{
    "subject_id": "sub_01HQZX8K4M2N7P",
    "images": ["<base64>", "<base64>", "<base64>"]
  }'`;

export const REJECTED_RESPONSE = `{
  "id": "vs_01HQZXB7D9E1",
  "decision": "rejected",
  "similarity": 0.2913,
  "threshold": 0.38,
  "failure_reason": "below_threshold"
}`;

export const INCONCLUSIVE_RESPONSE = `{
  "id": "vs_01HQZXC2F4G6",
  "decision": "inconclusive",
  "similarity": null,
  "threshold": 0.38,
  "failure_reason": "low_quality",
  "quality": { "sharpness": 0.19, "brightness": 0.22 }
}`;

export const WEBHOOK_VERIFY = `import crypto from "node:crypto";

export function verifySignature(rawBody, header, secret) {
  const [t, v1] = header.split(",").map((p) => p.split("=")[1]);

  // The timestamp is inside the signed payload, so a captured request
  // cannot be replayed later. Reject anything older than five minutes.
  if (Math.abs(Date.now() / 1000 - Number(t)) > 300) return false;

  const expected = crypto
    .createHmac("sha256", secret)
    .update(\`\${t}.\${rawBody}\`)
    .digest("hex");

  return crypto.timingSafeEqual(Buffer.from(v1), Buffer.from(expected));
}`;
