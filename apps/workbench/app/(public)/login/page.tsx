import { LoginForm } from "@/components/auth/LoginForm";

export default function LoginPage() {
  return (
    <main style={{ padding: "2rem", maxWidth: 360, margin: "4rem auto 0" }}>
      <h1>Workbench sign in</h1>
      <p style={{ opacity: 0.7, fontSize: "0.875rem" }}>
        Toee Tire customer service Copilot &amp; governance console.
      </p>
      <LoginForm />
    </main>
  );
}
