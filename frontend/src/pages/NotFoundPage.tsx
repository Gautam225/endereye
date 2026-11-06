import { Compass } from "lucide-react";
import { Link } from "react-router";

import { PageHeader } from "../components/PageHeader";
import { Card } from "../components/ui/Card";
import { EmptyState } from "../components/ui/Notice";

export function NotFoundPage() {
  return (
    <>
      <PageHeader title="Page not found" />
      <Card>
        <EmptyState icon={Compass} title="Nothing lives at this address">
          <Link to="/" className="font-medium text-accent underline-offset-4 hover:underline">
            Go to the start page
          </Link>
        </EmptyState>
      </Card>
    </>
  );
}
