import { z } from "zod";

/**
 * Client-side validation.
 *
 * Deliberately mirrors — never replaces — the server rules. Client validation
 * is a fast feedback loop; the server is the boundary that counts. Where the
 * two could drift (the common-password list), the client stays permissive and
 * lets the server be authoritative, so a user is never blocked by a stale copy.
 */

export const MIN_PASSWORD_LENGTH = 12;

const email = z
  .string()
  .min(1, "Enter your email address.")
  .email("That does not look like a valid email address.")
  .transform((value) => value.trim().toLowerCase());

const password = z
  .string()
  .min(MIN_PASSWORD_LENGTH, `Use at least ${MIN_PASSWORD_LENGTH} characters.`)
  .max(128, "That password is too long.");

export const loginSchema = z.object({
  email,
  password: z.string().min(1, "Enter your password."),
});

export const registerSchema = z.object({
  full_name: z.string().min(1, "Enter your name.").max(120),
  email,
  password,
  organization_name: z.string().max(120).optional(),
});

export const forgotPasswordSchema = z.object({ email });

export const resetPasswordSchema = z
  .object({
    password,
    confirm: z.string(),
  })
  .refine((values) => values.password === values.confirm, {
    message: "Both passwords must match.",
    path: ["confirm"],
  });

export const organizationSchema = z.object({
  name: z.string().min(2, "Use at least 2 characters.").max(120),
});

export type LoginValues = z.infer<typeof loginSchema>;
export type RegisterValues = z.infer<typeof registerSchema>;
export type ForgotPasswordValues = z.infer<typeof forgotPasswordSchema>;
export type ResetPasswordValues = z.infer<typeof resetPasswordSchema>;
export type OrganizationValues = z.infer<typeof organizationSchema>;

/**
 * A four-band strength meter.
 *
 * Length dominates on purpose: it is the property that actually resists
 * offline cracking, and composition rules ("one symbol!") are documented to
 * push people toward predictable patterns like `Password1!`.
 */
export function passwordStrength(value: string): {
  score: 0 | 1 | 2 | 3 | 4;
  label: string;
} {
  if (!value) return { score: 0, label: "" };

  let score = 0;
  if (value.length >= MIN_PASSWORD_LENGTH) score += 2;
  else if (value.length >= 8) score += 1;
  if (value.length >= 16) score += 1;
  if (/\s/.test(value) && value.length >= 16) score += 1; // passphrases
  if (new Set(value).size >= 10) score += 1;

  const clamped = Math.min(score, 4) as 0 | 1 | 2 | 3 | 4;
  return {
    score: clamped,
    label: ["Too short", "Weak", "Fair", "Good", "Strong"][clamped]!,
  };
}
