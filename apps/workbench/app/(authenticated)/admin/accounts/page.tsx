import { AccountsConsole } from "@/components/admin/AccountsConsole";

// Thin server shell for the account administration console (ADR-0089). The
// client console fetches accounts on mount; middleware already gates /admin/*.
export default function AdminAccountsPage() {
  return (
    <section>
      <h1>Accounts</h1>
      <AccountsConsole />
    </section>
  );
}
