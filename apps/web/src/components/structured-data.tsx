import { siteConfig } from "@/config/site";
import { faqGroups } from "@/lib/content/faq";
import { plans } from "@/lib/content/pricing";

/**
 * JSON-LD structured data.
 *
 * Search engines use this to render richer results — an FAQ page can surface its
 * questions directly, and a product can show its price. It costs nothing at
 * runtime because it is inert markup in the static HTML.
 *
 * The content is derived from the same modules the pages render, so the markup
 * can never claim a price the page does not show.
 */
function JsonLd({ data }: { data: object }) {
  return (
    <script
      type="application/ld+json"
      // Serialized from our own typed content modules, never user input.
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data) }}
    />
  );
}

export function OrganizationJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "Organization",
        name: siteConfig.name,
        url: siteConfig.url,
        description: siteConfig.description,
        email: siteConfig.email,
        contactPoint: {
          "@type": "ContactPoint",
          contactType: "customer support",
          email: siteConfig.email,
          url: `${siteConfig.url}/contact`,
        },
      }}
    />
  );
}

export function SoftwareApplicationJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "SoftwareApplication",
        name: siteConfig.name,
        applicationCategory: "SecurityApplication",
        operatingSystem: "Web-based API",
        description: siteConfig.description,
        url: siteConfig.url,
        offers: plans
          .filter((plan) => plan.price !== null)
          .map((plan) => ({
            "@type": "Offer",
            name: plan.name,
            price: plan.price,
            priceCurrency: "USD",
            description: plan.description,
            url: `${siteConfig.url}/pricing`,
          })),
      }}
    />
  );
}

export function FaqJsonLd() {
  return (
    <JsonLd
      data={{
        "@context": "https://schema.org",
        "@type": "FAQPage",
        mainEntity: faqGroups.flatMap((group) =>
          group.items.map((item) => ({
            "@type": "Question",
            name: item.question,
            acceptedAnswer: { "@type": "Answer", text: item.answer },
          })),
        ),
      }}
    />
  );
}
