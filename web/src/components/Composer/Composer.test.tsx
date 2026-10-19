import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { Composer } from "./Composer";

describe("Composer", () => {
  afterEach(() => cleanup());
  it("clears text on successful send and generates new id after edit", async () => {
    const onSend = vi.fn().mockResolvedValue(undefined);
    render(<Composer onSend={onSend} />);
    const area = screen.getByPlaceholderText("Message");
    fireEvent.change(area, { target: { value: "Hi" } });
    fireEvent.keyDown(area, { key: "Enter" });
    await waitFor(() => expect(onSend).toHaveBeenCalledWith("Hi", expect.any(String)));
    expect(area).toHaveValue("");
    const firstId = onSend.mock.calls[0]![1];
    fireEvent.change(area, { target: { value: "Again" } });
    fireEvent.keyDown(area, { key: "Enter" });
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend.mock.calls[1]![1]).not.toBe(firstId);
  });

  it("keeps text and reuses clientTurnId on failed send", async () => {
    const onSend = vi
      .fn()
      .mockRejectedValueOnce(new Error("fail"))
      .mockResolvedValueOnce(undefined);
    render(<Composer onSend={onSend} />);
    const area = screen.getByPlaceholderText("Message");
    fireEvent.change(area, { target: { value: "Retry me" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(1));
    expect(area).toHaveValue("Retry me");
    const firstId = onSend.mock.calls[0]![1];
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await waitFor(() => expect(onSend).toHaveBeenCalledTimes(2));
    expect(onSend.mock.calls[1]![1]).toBe(firstId);
  });

  it("calls onTextChange and respects initialText", () => {
    const onTextChange = vi.fn();
    const { rerender } = render(
      <Composer onSend={vi.fn()} initialText="seed" onTextChange={onTextChange} />,
    );
    expect(screen.getByPlaceholderText("Message")).toHaveValue("seed");
    fireEvent.change(screen.getByPlaceholderText("Message"), { target: { value: "edit" } });
    expect(onTextChange).toHaveBeenCalledWith("edit");
    rerender(<Composer onSend={vi.fn()} initialText="fresh" onTextChange={onTextChange} />);
    expect(screen.getByPlaceholderText("Message")).toHaveValue("fresh");
  });

  it("Shift+Enter does not send", () => {
    const onSend = vi.fn();
    render(<Composer onSend={onSend} />);
    const area = screen.getByPlaceholderText("Message");
    fireEvent.change(area, { target: { value: "Line" } });
    fireEvent.keyDown(area, { key: "Enter", shiftKey: true });
    expect(onSend).not.toHaveBeenCalled();
  });
});
