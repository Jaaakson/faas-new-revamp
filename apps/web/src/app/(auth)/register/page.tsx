import type { Metadata } from "next";
import { Suspense } from "react";

import { RegisterForm } from "@/components/auth/register-form";

export const metadata: Metadata = {
  title: "Create your account",
  description: "Start with 1,000 free verifications a month. No card required.",
  robots: { index: false, follow: false },
};

export default function RegisterPage() {
  return (
    <Suspense fallback={<div className="h-96" aria-hidden />}>
      <RegisterForm />
    </Suspense>
  );
}
