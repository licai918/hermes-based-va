import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { WORKBENCH_ROLES } from "@toee/shared";
import { UserMenu } from "./UserMenu";

describe("UserMenu", () => {
  it("shows the signed-in username and role label", () => {
    render(<UserMenu username="alice" role={WORKBENCH_ROLES.supervisor} />);
    expect(screen.getByText("alice")).toBeInTheDocument();
    expect(screen.getByText("Workbench Supervisor")).toBeInTheDocument();
  });

  it("posts to the logout endpoint then signs the operator out", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(null, { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const onSignedOut = vi.fn();

    render(
      <UserMenu
        username="alice"
        role={WORKBENCH_ROLES.rep}
        onSignedOut={onSignedOut}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /logout/i }));

    await waitFor(() => expect(onSignedOut).toHaveBeenCalledTimes(1));
    expect(fetchMock).toHaveBeenCalledWith("/api/auth/logout", {
      method: "POST",
    });
    vi.unstubAllGlobals();
  });
});
