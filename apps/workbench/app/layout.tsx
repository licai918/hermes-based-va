import type { ReactNode } from "react";

export const metadata = {
  title: "Toee Hermes Workbench",
  description: "Copilot and governance console for Toee Tire customer service.",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
