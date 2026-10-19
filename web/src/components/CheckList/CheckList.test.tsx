import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CheckList, checksFromSeatDetail } from "./CheckList";
import styles from "./CheckList.module.css";

describe("CheckList", () => {
  it("maps seat checks to pass/fail", () => {
    const items = checksFromSeatDetail([{ name: "limits", passed: true, detail: "ok" }]);
    const { container } = render(<CheckList items={items} />);
    expect(container.querySelector(`.${styles.srOnly}`)).toHaveTextContent("pass");
    expect(screen.getByText("ok")).toBeInTheDocument();
  });
});
