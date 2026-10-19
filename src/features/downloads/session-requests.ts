import { ApiError, asApiError, type RequestOptions } from "./api.ts";
import type { Session } from "./contracts.ts";
import { SessionScope } from "./session.ts";

type SessionRequestOptions = {
  scope: SessionScope;
  current: () => Session | null;
  refresh: (signal: AbortSignal) => Promise<Session>;
  accept: (session: Session) => void;
  expired: (problem: ApiError, session: Session) => void;
  refreshError: (problem: ApiError) => void;
};

/** Shares cookie renewal; only a definitive rejection can replay one operation. */
export class SessionRequests {
  private options: SessionRequestOptions;
  private pending: Promise<Session> | null = null;

  constructor(options: SessionRequestOptions) {
    this.options = options;
  }

  renew(previous: Session): Promise<Session> {
    const latest = this.options.current();
    if (!latest) return Promise.reject(new ApiError({ code: "ABORTED" }));
    if (latest.authenticated && previous.authenticated && latest.csrf_token !== previous.csrf_token)
      return Promise.resolve(latest);
    if (this.pending) return this.pending;
    const request = this.options.scope.run(async (signal) => {
      const fresh = await this.options.refresh(signal);
      if (signal.aborted) throw new ApiError({ code: "ABORTED" });
      // A newer session may have won while this response was in flight.
      const active = this.options.current();
      if (!active) throw new ApiError({ code: "ABORTED" });
      if (
        active.authenticated &&
        previous.authenticated &&
        active.csrf_token !== previous.csrf_token
      )
        return active;
      this.options.accept(fresh);
      return fresh;
    });
    this.pending = request;
    const clear = () => {
      if (this.pending === request) this.pending = null;
    };
    void request.then(clear, clear);
    return request;
  }

  run<T>(
    operation: (csrf: string, options: RequestOptions) => Promise<T>,
    external?: AbortSignal,
  ): Promise<T> {
    return this.options.scope.run(async (signal) => {
      if (signal.aborted) throw new ApiError({ code: "ABORTED" });
      const current = this.options.current();
      if (!current?.authenticated)
        throw new ApiError({ code: "UNAUTHORIZED", status: 401, action: "login" });
      try {
        return await operation(current.csrf_token, { signal });
      } catch (error) {
        if (signal.aborted) throw new ApiError({ code: "ABORTED" });
        const problem = asApiError(error);
        const unauthorized = problem.status === 401 || problem.code === "UNAUTHORIZED";
        if (!unauthorized && problem.code !== "CSRF_FAILED") throw problem;
        if (unauthorized && current.password_required !== false) {
          this.options.expired(problem, current);
          throw problem;
        }
        let fresh: Session;
        try {
          fresh = await this.renew(current);
        } catch (refreshError) {
          const failure = asApiError(refreshError);
          if (failure.code !== "ABORTED") this.options.refreshError(failure);
          throw current.password_required === false ? failure : problem;
        }
        if (signal.aborted) throw new ApiError({ code: "ABORTED" });
        if (!fresh.authenticated) {
          const failure = new ApiError({ code: "UNAUTHORIZED", status: 401, action: "login" });
          this.options.expired(failure, fresh);
          throw failure;
        }
        // Protected sessions retain their explicit retry/login behavior. Passwordless
        // 401/CSRF responses are rejected before an action; keep the original intent.
        if (current.password_required !== false || fresh.password_required !== false) throw problem;
        try {
          return await operation(fresh.csrf_token, { signal });
        } catch (retryError) {
          if (signal.aborted) throw new ApiError({ code: "ABORTED" });
          const failure = asApiError(retryError);
          if (failure.status === 401 || failure.code === "UNAUTHORIZED")
            this.options.expired(failure, fresh);
          throw failure;
        }
      }
    }, external);
  }
}
