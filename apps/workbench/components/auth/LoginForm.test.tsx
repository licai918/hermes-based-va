import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LoginForm } from "./LoginForm";

function fillAndSubmit(username: string, password: string) {
  fireEvent.change(screen.getByLabelText("Username"), {
    target: { value: username },
  });
  fireEvent.change(screen.getByLabelText("Password"), {
    target: { value: password },
  });
  fireEvent.click(screen.getByRole("button", { name: /sign in/i }));
}

describe("LoginForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("never lets credentials be submitted as a URL query (form must be POST)", () => {
    // A <form> with no method defaults to GET and no action defaults to the
    // current URL. React's onSubmit calls preventDefault, but it is only
    // attached AFTER hydration -- submit inside that window (a fast typist
    // pressing Enter, a slow bundle, a failed hydration) and the browser does
    // the native thing: GET /login?username=...&password=...
    //
    // That puts the password in the URL bar, browser history, the server access
    // log, and any Referer sent onward. Observed for real while driving this
    // page with a browser whose hydration had not completed.
    //
    // method="post" costs nothing after hydration (preventDefault still wins)
    // and removes the leak entirely in that window: credentials go in the body.
    const { container } = render(<LoginForm />);
    const form = container.querySelector("form");

    expect(form).not.toBeNull();
    expect(form?.getAttribute("method")?.toLowerCase()).toBe("post");
  });

  it("posts credentials and calls onSuccess on 200", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ user: {} }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const onSuccess = vi.fn();

    render(<LoginForm onSuccess={onSuccess} />);
    fillAndSubmit("alice", "Sup3r-secret!");

    await waitFor(() => expect(onSuccess).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/login", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ username: "alice", password: "Sup3r-secret!" }),
    });
  });

  it("shows an invalid-credentials message on 401 and does not navigate", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: "invalid credentials" }), {
          status: 401,
        }),
      ),
    );
    const onSuccess = vi.fn();

    render(<LoginForm onSuccess={onSuccess} />);
    fillAndSubmit("alice", "wrong");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /invalid username or password/i,
    );
    expect(onSuccess).not.toHaveBeenCalled();
  });

  it("shows a lockout message on 423", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({}), { status: 423 })),
    );

    render(<LoginForm />);
    fillAndSubmit("alice", "whatever");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /locked/i,
    );
  });

  it("shows a disabled-account message on 403", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({}), { status: 403 })),
    );

    render(<LoginForm />);
    fillAndSubmit("alice", "whatever");

    expect(await screen.findByRole("alert")).toHaveTextContent(/disabled/i);
  });
});
