import type { EmployeeRow, NoticeRow } from "@/lib/types";

/**
 * A notice row joined to the employee it belongs to — the shape /notices reads.
 * Declared here (not in page.tsx) because Next.js page files may only export
 * route symbols, and the list/preview components share these shapes.
 */
export interface NoticeWithEmployee extends NoticeRow {
  employee: Pick<EmployeeRow, "id" | "name" | "email" | "role">;
}

/** One dispatched notice as returned by POST /api/notices/send. */
export interface SendDispatch {
  notice_id: string;
  /** ISO timestamp — the single-use signing token's expiry. */
  expires_at?: string;
}

/** One notice the server refused to send (e.g. already signed). */
export interface SendBlock {
  notice_id: string;
  reason: string;
}
