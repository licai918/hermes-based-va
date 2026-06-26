import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { WORKBENCH_ROLES } from "@toee/shared";
import type { PublicAccount } from "@/lib/bff/admin/accounts";
import { ErrorBannerProvider } from "@/components/shell/error-banner";
import { AccountsConsole, AccountsConsoleView } from "./AccountsConsole";

const NOW = 1_700_000_000_000;

const ACCOUNTS: PublicAccount[] = [
  {
    accountId: "seed-admin",
    username: "admin",
    role: WORKBENCH_ROLES.admin,
    status: "active",
    lastLoginAt: null,
    createdAt: NOW - 60_000,
  },
  {
    accountId: "seed-rep",
    username: "rep",
    role: WORKBENCH_ROLES.rep,
    status: "disabled",
    lastLoginAt: NOW - 120_000,
    createdAt: NOW - 60_000,
  },
];

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status });
}

function baseViewProps() {
  return {
    accounts: ACCOUNTS,
    now: NOW,
    busy: false,
    createError: null as string | null,
    createErrors: null as string[] | null,
    onCreate: vi.fn(),
    onChangeRole: vi.fn(),
    onDisable: vi.fn(),
  };
}

describe("AccountsConsoleView", () => {
  it("renders the accounts table with role labels and never references passwordHash", () => {
    const { container } = render(<AccountsConsoleView {...baseViewProps()} />);
    expect(screen.getByText("admin")).toBeInTheDocument();
    const adminRole = screen.getByLabelText("Role for admin");
    expect(adminRole).toHaveValue(WORKBENCH_ROLES.admin);
    expect(
      within(adminRole).getByRole("option", { name: "Workbench Admin" }),
    ).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/passwordhash/i);
  });

  it("shows 'never' for an account that has never logged in", () => {
    render(<AccountsConsoleView {...baseViewProps()} />);
    expect(screen.getByText("never")).toBeInTheDocument();
  });

  it("submits the create form with username, role, and password", () => {
    const onCreate = vi.fn();
    render(<AccountsConsoleView {...baseViewProps()} onCreate={onCreate} />);

    fireEvent.change(screen.getByLabelText("Username"), {
      target: { value: "casey" },
    });
    fireEvent.change(screen.getByLabelText("Password"), {
      target: { value: "Workbench123!" },
    });
    fireEvent.change(screen.getByLabelText("Role"), {
      target: { value: WORKBENCH_ROLES.supervisor },
    });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(onCreate).toHaveBeenCalledWith({
      username: "casey",
      role: WORKBENCH_ROLES.supervisor,
      password: "Workbench123!",
    });
  });

  it("renders password-policy errors[] from a failed create", () => {
    render(
      <AccountsConsoleView
        {...baseViewProps()}
        createError="password does not meet policy"
        createErrors={["at least 12 characters", "needs a digit"]}
      />,
    );
    expect(screen.getByText("at least 12 characters")).toBeInTheDocument();
    expect(screen.getByText("needs a digit")).toBeInTheDocument();
  });

  it("renders a duplicate-username message", () => {
    render(
      <AccountsConsoleView {...baseViewProps()} createError="username already exists" />,
    );
    expect(screen.getByText(/already exists/i)).toBeInTheDocument();
  });

  it("invokes onChangeRole when a row role is changed", () => {
    const onChangeRole = vi.fn();
    render(<AccountsConsoleView {...baseViewProps()} onChangeRole={onChangeRole} />);
    fireEvent.change(screen.getByLabelText("Role for admin"), {
      target: { value: WORKBENCH_ROLES.supervisor },
    });
    expect(onChangeRole).toHaveBeenCalledWith("seed-admin", WORKBENCH_ROLES.supervisor);
  });

  it("invokes onDisable for an active account and disables the control for a disabled one", () => {
    const onDisable = vi.fn();
    render(<AccountsConsoleView {...baseViewProps()} onDisable={onDisable} />);
    fireEvent.click(screen.getByRole("button", { name: "Disable admin" }));
    expect(onDisable).toHaveBeenCalledWith("seed-admin");
    expect(screen.getByRole("button", { name: "Disable rep" })).toBeDisabled();
  });
});

describe("AccountsConsole (fetching container)", () => {
  afterEach(() => vi.unstubAllGlobals());

  function renderConsole() {
    return render(
      <ErrorBannerProvider>
        <AccountsConsole />
      </ErrorBannerProvider>,
    );
  }

  it("loads accounts on mount and shows a seeded username", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse({ accounts: ACCOUNTS })),
    );
    const { container } = renderConsole();
    expect(await screen.findByText("admin")).toBeInTheDocument();
    expect(container.innerHTML).not.toMatch(/passwordhash/i);
  });

  it("shows the policy errors[] when create returns 400", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/admin/accounts" && method === "POST") {
        return Promise.resolve(
          jsonResponse(
            { error: "password does not meet policy", errors: ["at least 12 characters"] },
            400,
          ),
        );
      }
      return Promise.resolve(jsonResponse({ accounts: ACCOUNTS }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();
    await screen.findByText("admin");

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "casey" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "short" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText("at least 12 characters")).toBeInTheDocument();
  });

  it("shows a duplicate message when create returns 409", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (url === "/api/admin/accounts" && method === "POST") {
        return Promise.resolve(jsonResponse({ error: "username already exists" }, 409));
      }
      return Promise.resolve(jsonResponse({ accounts: ACCOUNTS }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();
    await screen.findByText("admin");

    fireEvent.change(screen.getByLabelText("Username"), { target: { value: "admin" } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "Workbench123!" } });
    fireEvent.click(screen.getByRole("button", { name: /create account/i }));

    expect(await screen.findByText(/already exists/i)).toBeInTheDocument();
  });

  it("PATCHes a role change and POSTs a disable", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const method = init?.method ?? "GET";
      if (method === "PATCH") {
        return Promise.resolve(jsonResponse({ account: ACCOUNTS[0] }));
      }
      if (url.endsWith("/disable")) {
        return Promise.resolve(jsonResponse({ account: ACCOUNTS[0] }));
      }
      return Promise.resolve(jsonResponse({ accounts: ACCOUNTS }));
    });
    vi.stubGlobal("fetch", fetchMock);
    renderConsole();
    await screen.findByText("admin");

    fireEvent.change(screen.getByLabelText("Role for admin"), {
      target: { value: WORKBENCH_ROLES.supervisor },
    });
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/seed-admin/role", {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ role: WORKBENCH_ROLES.supervisor }),
      }),
    );

    fireEvent.click(screen.getByRole("button", { name: "Disable admin" }));
    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith("/api/admin/accounts/seed-admin/disable", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: undefined,
      }),
    );
  });
});
