import { Dashboard } from "@/components/dashboard";
import { getDashboardSnapshot } from "@/lib/data";

export const dynamic = "force-dynamic";
export const revalidate = 0;

export default async function Home() {
  const snapshot = await getDashboardSnapshot();
  return <Dashboard initialSnapshot={snapshot} />;
}
