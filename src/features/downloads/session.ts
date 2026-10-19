import { ApiError } from "./api.ts";
/** Invalidates every owned request when authentication changes, even if fetch ignores abort. */
export class SessionScope {
  private generation = 0;
  private requests = new Set<AbortController>();
  reset(): void {
    this.generation += 1;
    for (const controller of this.requests) controller.abort();
    this.requests.clear();
  }
  async run<T>(operation: (signal: AbortSignal) => Promise<T>, external?: AbortSignal): Promise<T> {
    const generation = this.generation;
    const controller = new AbortController();
    this.requests.add(controller);
    const abort = () => controller.abort();
    external?.addEventListener("abort", abort, { once: true });
    if (external?.aborted) abort();
    try {
      const result = await operation(controller.signal);
      if (generation !== this.generation || controller.signal.aborted)
        throw new ApiError({ code: "ABORTED" });
      return result;
    } catch (error) {
      if (generation !== this.generation || controller.signal.aborted)
        throw new ApiError({ code: "ABORTED" });
      throw error;
    } finally {
      this.requests.delete(controller);
      external?.removeEventListener("abort", abort);
    }
  }
}
