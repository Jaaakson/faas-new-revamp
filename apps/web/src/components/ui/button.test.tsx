import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("renders its label", () => {
    render(<Button>Start free</Button>);
    expect(screen.getByRole("button", { name: "Start free" })).toBeInTheDocument();
  });

  it("applies the variant classes", () => {
    render(<Button variant="destructive">Revoke key</Button>);
    expect(screen.getByRole("button")).toHaveClass("bg-destructive");
  });

  it("lets a caller override a conflicting utility", () => {
    // This is the whole reason `cn` uses tailwind-merge. Without it the
    // variant's background wins by stylesheet order and the override is a
    // silent no-op.
    render(<Button className="bg-success">Verified</Button>);
    const button = screen.getByRole("button");
    expect(button).toHaveClass("bg-success");
    expect(button).not.toHaveClass("bg-primary");
  });

  it("renders as a link when asChild is set", () => {
    // A <button> wrapping an <a> is invalid HTML and breaks keyboard and
    // screen-reader semantics, so this path must stay working.
    render(
      <Button asChild>
        <a href="/docs">Read the docs</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Read the docs" });
    expect(link).toHaveAttribute("href", "/docs");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("is disabled when asked", () => {
    render(<Button disabled>Submit</Button>);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
