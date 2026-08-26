"use client";

import { CodeTabs } from "@/components/docs/code-tabs";

/**
 * Canonical four-language samples for the endpoints an integrator actually
 * calls.
 *
 * Kept in one file rather than inline in each MDX page, for a reason that shows
 * up the first time the API changes: nine copies of a request body drift, and
 * the ones nobody reread stay wrong. A single definition means a contract change
 * is one edit.
 *
 * Every sample is a complete, runnable program — imports, error handling, and
 * the three-way decision branch included. Snippets that omit error handling
 * teach integrators to omit it too, and with an authentication API that is not
 * a style question.
 */

const BASE = "https://api.fvas.io/v1";

function samples(
  curl: string,
  node: string,
  python: string,
  go: string,
): { language: string; label: string; code: string }[] {
  return [
    { language: "curl", label: "cURL", code: curl.trim() },
    { language: "node", label: "Node.js", code: node.trim() },
    { language: "python", label: "Python", code: python.trim() },
    { language: "go", label: "Go", code: go.trim() },
  ];
}

export function CreateSubjectSample() {
  return (
    <CodeTabs
      samples={samples(
        `
curl -X POST ${BASE}/subjects \\
  -H "Authorization: Bearer $FVAS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d '{
    "external_id": "user_84213",
    "display_name": "Rani Wulandari",
    "consent_reference": "consent_2026_07_30_84213"
  }'
`,
        `
const response = await fetch("${BASE}/subjects", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.FVAS_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    external_id: "user_84213",
    display_name: "Rani Wulandari",
    consent_reference: "consent_2026_07_30_84213",
  }),
});

if (!response.ok) {
  const { error } = await response.json();
  // 409 means this external_id already exists — usually a retry, not a bug.
  throw new Error(\`\${error.code}: \${error.message}\`);
}

const subject = await response.json();
console.log(subject.id); // sub_01HQZX8K4M2N7P
`,
        `
import os
import httpx

response = httpx.post(
    "${BASE}/subjects",
    headers={"Authorization": f"Bearer {os.environ['FVAS_API_KEY']}"},
    json={
        "external_id": "user_84213",
        "display_name": "Rani Wulandari",
        "consent_reference": "consent_2026_07_30_84213",
    },
)

if response.status_code == 409:
    # Already exists. Idempotent retries land here; fetch instead of failing.
    subject = httpx.get(
        "${BASE}/subjects/ext_user_84213",
        headers={"Authorization": f"Bearer {os.environ['FVAS_API_KEY']}"},
    ).json()
else:
    response.raise_for_status()
    subject = response.json()

print(subject["id"])  # sub_01HQZX8K4M2N7P
`,
        `
package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
)

type Subject struct {
	ID         string \`json:"id"\`
	ExternalID string \`json:"external_id"\`
	Status     string \`json:"status"\`
}

func main() {
	body, _ := json.Marshal(map[string]string{
		"external_id":       "user_84213",
		"display_name":      "Rani Wulandari",
		"consent_reference": "consent_2026_07_30_84213",
	})

	req, _ := http.NewRequest("POST", "${BASE}/subjects", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+os.Getenv("FVAS_API_KEY"))
	req.Header.Set("Content-Type", "application/json")

	res, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer res.Body.Close()

	if res.StatusCode != http.StatusCreated {
		panic(fmt.Sprintf("create subject failed: %s", res.Status))
	}

	var subject Subject
	json.NewDecoder(res.Body).Decode(&subject)
	fmt.Println(subject.ID) // sub_01HQZX8K4M2N7P
}
`,
      )}
    />
  );
}

export function EnrollSample() {
  return (
    <CodeTabs
      samples={samples(
        `
# Three captures of the same person, slightly different angles.
curl -X POST ${BASE}/enrollments \\
  -H "Authorization: Bearer $FVAS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -d "{
    \\"subject_id\\": \\"sub_01HQZX8K4M2N7P\\",
    \\"images\\": [\\"$(base64 -w0 front.jpg)\\", \\"$(base64 -w0 left.jpg)\\", \\"$(base64 -w0 right.jpg)\\"]
  }"
`,
        `
import { readFile } from "node:fs/promises";

const encode = async (path) => (await readFile(path)).toString("base64");

const response = await fetch("${BASE}/enrollments", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.FVAS_API_KEY}\`,
    "Content-Type": "application/json",
  },
  body: JSON.stringify({
    subject_id: "sub_01HQZX8K4M2N7P",
    images: await Promise.all(["front.jpg", "left.jpg", "right.jpg"].map(encode)),
  }),
});

const result = await response.json();

if (response.status === 409 && result.error?.code === "duplicate_face_detected") {
  // This face already belongs to someone else. A decision for a human, not a
  // retry — the details say who it matched and how closely.
  console.warn("Duplicate of", result.error.details.matched_subject_id);
} else if (response.status === 422) {
  // No usable frame. Every image comes back with a reason and guidance.
  for (const image of result.error.details.images) {
    if (!image.accepted) console.log(\`frame \${image.index}: \${image.guidance}\`);
  }
} else if (!response.ok) {
  throw new Error(result.error.message);
} else {
  console.log(\`profile v\${result.face_profile.version}\`);
}
`,
        `
import base64
import os
import httpx


def encode(path: str) -> str:
    with open(path, "rb") as handle:
        return base64.b64encode(handle.read()).decode()


response = httpx.post(
    "${BASE}/enrollments",
    headers={"Authorization": f"Bearer {os.environ['FVAS_API_KEY']}"},
    json={
        "subject_id": "sub_01HQZX8K4M2N7P",
        "images": [encode(p) for p in ("front.jpg", "left.jpg", "right.jpg")],
    },
    timeout=30.0,
)
result = response.json()

if response.status_code == 409:
    # Already enrolled under another identity. Surface it; do not retry.
    details = result["error"]["details"]
    print("duplicate of", details["matched_subject_id"], details["similarity"])
elif response.status_code == 422:
    for image in result["error"]["details"]["images"]:
        if not image["accepted"]:
            print(f"frame {image['index']}: {image['guidance']}")
else:
    response.raise_for_status()
    print("profile v", result["face_profile"]["version"])
`,
        `
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
)

func encode(path string) string {
	data, err := os.ReadFile(path)
	if err != nil {
		panic(err)
	}
	return base64.StdEncoding.EncodeToString(data)
}

func main() {
	body, _ := json.Marshal(map[string]any{
		"subject_id": "sub_01HQZX8K4M2N7P",
		"images":     []string{encode("front.jpg"), encode("left.jpg"), encode("right.jpg")},
	})

	req, _ := http.NewRequest("POST", "${BASE}/enrollments", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+os.Getenv("FVAS_API_KEY"))
	req.Header.Set("Content-Type", "application/json")

	res, _ := http.DefaultClient.Do(req)
	defer res.Body.Close()

	var result map[string]any
	json.NewDecoder(res.Body).Decode(&result)

	switch res.StatusCode {
	case http.StatusConflict:
		// Duplicate face: a decision for a human, not something to retry.
		fmt.Println("duplicate:", result["error"])
	case http.StatusUnprocessableEntity:
		fmt.Println("no usable frame:", result["error"])
	case http.StatusCreated:
		profile := result["face_profile"].(map[string]any)
		fmt.Println("profile v", profile["version"])
	default:
		panic(res.Status)
	}
}
`,
      )}
    />
  );
}

export function VerifySample() {
  return (
    <CodeTabs
      samples={samples(
        `
curl -X POST ${BASE}/verifications \\
  -H "Authorization: Bearer $FVAS_API_KEY" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: $(uuidgen)" \\
  -d "{
    \\"subject_id\\": \\"sub_01HQZX8K4M2N7P\\",
    \\"image\\": \\"$(base64 -w0 capture.jpg)\\"
  }"
`,
        `
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";

const response = await fetch("${BASE}/verifications", {
  method: "POST",
  headers: {
    Authorization: \`Bearer \${process.env.FVAS_API_KEY}\`,
    "Content-Type": "application/json",
    // Safe to retry: a repeat replays the first answer instead of
    // re-running the pipeline or charging your quota twice.
    "Idempotency-Key": randomUUID(),
  },
  body: JSON.stringify({
    subject_id: "sub_01HQZX8K4M2N7P",
    image: (await readFile("capture.jpg")).toString("base64"),
  }),
});

if (response.status === 429) {
  const wait = Number(response.headers.get("Retry-After") ?? 1);
  throw new Error(\`Rate limited. Retry in \${wait}s.\`);
}

const result = await response.json();

// Three outcomes, never two. Collapsing "inconclusive" into "rejected" would
// tell your user they are an impostor when the truth is the room is too dark.
switch (result.decision) {
  case "verified":
    // \`confidence\` is "high" | "medium" | "low" — a low band on a high-value
    // action is exactly where you should demand a second factor.
    grantAccess(result.confidence);
    break;
  case "rejected":
    denyAndLog(result.similarity, result.threshold);
    break;
  case "inconclusive":
    askToRetry(result.guidance);
    break;
}
`,
        `
import base64
import os
import uuid

import httpx

with open("capture.jpg", "rb") as handle:
    image = base64.b64encode(handle.read()).decode()

response = httpx.post(
    "${BASE}/verifications",
    headers={
        "Authorization": f"Bearer {os.environ['FVAS_API_KEY']}",
        # Safe to retry: a repeat replays the first answer rather than
        # re-running the pipeline or charging quota twice.
        "Idempotency-Key": str(uuid.uuid4()),
    },
    json={"subject_id": "sub_01HQZX8K4M2N7P", "image": image},
    timeout=10.0,
)

if response.status_code == 429:
    raise RuntimeError(f"rate limited, retry in {response.headers['Retry-After']}s")

response.raise_for_status()
result = response.json()

# Three outcomes, never two.
if result["decision"] == "verified":
    grant_access(confidence=result["confidence"])
elif result["decision"] == "rejected":
    deny_and_log(result["similarity"], result["threshold"])
else:  # inconclusive — a capture problem, not an identity judgement
    ask_to_retry(result["guidance"])
`,
        `
package main

import (
	"bytes"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"

	"github.com/google/uuid"
)

type Verification struct {
	Decision   string   \`json:"decision"\`
	Similarity *float64 \`json:"similarity"\`
	Threshold  float64  \`json:"threshold"\`
	Confidence *string  \`json:"confidence"\`
	Guidance   *string  \`json:"guidance"\`
}

func main() {
	image, _ := os.ReadFile("capture.jpg")
	body, _ := json.Marshal(map[string]string{
		"subject_id": "sub_01HQZX8K4M2N7P",
		"image":      base64.StdEncoding.EncodeToString(image),
	})

	req, _ := http.NewRequest("POST", "${BASE}/verifications", bytes.NewReader(body))
	req.Header.Set("Authorization", "Bearer "+os.Getenv("FVAS_API_KEY"))
	req.Header.Set("Content-Type", "application/json")
	// Safe to retry: a repeat replays the first answer.
	req.Header.Set("Idempotency-Key", uuid.NewString())

	res, err := http.DefaultClient.Do(req)
	if err != nil {
		panic(err)
	}
	defer res.Body.Close()

	if res.StatusCode == http.StatusTooManyRequests {
		panic("rate limited, retry after " + res.Header.Get("Retry-After") + "s")
	}

	var result Verification
	json.NewDecoder(res.Body).Decode(&result)

	// Three outcomes, never two.
	switch result.Decision {
	case "verified":
		fmt.Println("verified, confidence", *result.Confidence)
	case "rejected":
		fmt.Println("not this person:", *result.Similarity, "<", result.Threshold)
	case "inconclusive":
		fmt.Println("could not decide:", *result.Guidance)
	}
}
`,
      )}
    />
  );
}

export function WebhookVerifySample() {
  return (
    <CodeTabs
      samples={samples(
        `
# Signature format: t=<unix seconds>,v1=<hex hmac-sha256>
# Signed payload is "{timestamp}.{raw body}" — sign the RAW bytes, not
# a re-serialised object, or the digest will not match.
Fvas-Signature: t=1753859051,v1=5257a869e7ec…
Fvas-Event-Id: evt_01HQZXB…
`,
        `
import { createHmac, timingSafeEqual } from "node:crypto";

const TOLERANCE_SECONDS = 300;

export function verifyWebhook(rawBody, header, secret) {
  const parts = Object.fromEntries(
    header.split(",").map((part) => part.split("=", 2)),
  );

  // The timestamp is inside the signed payload, so a captured request cannot
  // be replayed later. Reject anything older than five minutes.
  const age = Math.abs(Date.now() / 1000 - Number(parts.t));
  if (!Number.isFinite(age) || age > TOLERANCE_SECONDS) return false;

  const expected = createHmac("sha256", secret)
    .update(\`\${parts.t}.\${rawBody}\`)
    .digest("hex");

  // Constant-time. A plain === leaks how many bytes matched.
  const a = Buffer.from(expected, "hex");
  const b = Buffer.from(parts.v1 ?? "", "hex");
  return a.length === b.length && timingSafeEqual(a, b);
}
`,
        `
import hashlib
import hmac
import time

TOLERANCE_SECONDS = 300


def verify_webhook(raw_body: bytes, header: str, secret: str) -> bool:
    parts = dict(part.split("=", 1) for part in header.split(","))

    # The timestamp is inside the signed payload, so a captured request cannot
    # be replayed later. Reject anything older than five minutes.
    if abs(time.time() - int(parts["t"])) > TOLERANCE_SECONDS:
        return False

    expected = hmac.new(
        secret.encode(),
        f"{parts['t']}.{raw_body.decode()}".encode(),
        hashlib.sha256,
    ).hexdigest()

    # Constant-time. A plain == leaks how many bytes matched.
    return hmac.compare_digest(expected, parts.get("v1", ""))
`,
        `
package fvas

import (
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"math"
	"strconv"
	"strings"
	"time"
)

const toleranceSeconds = 300

func VerifyWebhook(rawBody []byte, header, secret string) bool {
	parts := map[string]string{}
	for _, part := range strings.Split(header, ",") {
		kv := strings.SplitN(part, "=", 2)
		if len(kv) == 2 {
			parts[kv[0]] = kv[1]
		}
	}

	ts, err := strconv.ParseInt(parts["t"], 10, 64)
	if err != nil {
		return false
	}
	// The timestamp is signed, so a captured request cannot be replayed later.
	if math.Abs(float64(time.Now().Unix()-ts)) > toleranceSeconds {
		return false
	}

	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(parts["t"] + "." + string(rawBody)))
	expected := mac.Sum(nil)

	given, err := hex.DecodeString(parts["v1"])
	if err != nil {
		return false
	}
	// Constant-time. A plain comparison leaks how many bytes matched.
	return hmac.Equal(expected, given)
}
`,
      )}
    />
  );
}
