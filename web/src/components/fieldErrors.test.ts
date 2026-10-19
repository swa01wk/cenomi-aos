import { describe, expect, it } from "vitest";
import type { Problem } from "../api/problems";
import { fieldErrorsFromProblem, pointerToFieldName } from "./fieldErrors";

describe("fieldErrors", () => {
  it("maps pointer to field name", () => {
    expect(pointerToFieldName("/content/quantity")).toBe("quantity");
  });

  it("builds map from validation problem", () => {
    const problem = {
      type: "x",
      title: "Invalid",
      status: 422,
      code: "validation_failed",
      errors: [{ pointer: "/content/quantity", message: "Enter a whole number." }],
    } as Problem;
    expect(fieldErrorsFromProblem(problem).get("quantity")).toBe("Enter a whole number.");
  });
});
