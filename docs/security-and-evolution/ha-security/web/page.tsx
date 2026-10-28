import { getServerSession } from "next-auth/next";

import { authOptions } from "@/auth";

import { ShopClient } from "./ShopClient";

async function requireSession() {
  const session = await getServerSession(authOptions);
  if (!session) throw new Error("Unauthenticated");
  return session;
}

export default async function ShopPage() {
  await requireSession();

  return (
    <main className="flex flex-col gap-4 p-8">
      <div>
        <h1 className="text-2xl font-semibold">Shop</h1>
        <p className="mt-1 text-sm text-zinc-600 dark:text-zinc-400">
          Everything the record knows about one day: every door edge and keypad press, the
          verdict the judge reached, and the picture taken at that moment.
        </p>
      </div>

      <ShopClient />
    </main>
  );
}
