import type { Job } from "./contracts.ts";
export type JobEntities = ReadonlyMap<string, Job>;
export const isActive = (job: Job) => job.status === "queued" || job.status === "running";
/** List membership never replaces canonical snapshots; revisions are authoritative. */
export function mergeJobs(current: JobEntities, incoming: readonly Job[]): JobEntities {
  let changed = false;
  const next = new Map(current);
  for (const job of incoming) {
    const previous = next.get(job.id);
    if (!previous || job.revision > previous.revision) {
      next.set(job.id, job);
      changed = true;
    }
  }
  return changed ? next : current;
}
export function orderedJobs(current: JobEntities): Job[] {
  return [...current.values()].sort(
    (left, right) =>
      Date.parse(right.created_at) - Date.parse(left.created_at) || left.id.localeCompare(right.id),
  );
}
export function activeJobs(current: JobEntities): Job[] {
  return orderedJobs(current).filter(isActive).reverse();
}
export function removeJob(current: JobEntities, id: string): JobEntities {
  const next = new Map(current);
  next.delete(id);
  return next;
}
