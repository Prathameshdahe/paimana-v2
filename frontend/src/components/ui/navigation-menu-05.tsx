import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import * as Popover from "@radix-ui/react-popover";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/formatters";
import { useRole } from "@/lib/auth/RoleContext";
import { canOpen } from "@/lib/auth/access";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";

/** who sees which link: the route map in lib/auth/access.ts */
type NavItem = { title: string; href: string; end: boolean };

const navigationMenuItems: NavItem[] = [
  { title: "Home", href: "/", end: true },
  { title: "Command", href: "/command", end: false },
  { title: "External factors", href: "/external", end: false },
  { title: "Bottlenecks", href: "/bottlenecks", end: false },
  { title: "Agencies", href: "/agencies", end: false },
  { title: "Radar", href: "/radar", end: false },
  { title: "Models", href: "/models", end: false },
  { title: "Workers", href: "/workers", end: false },
  { title: "Approvals", href: "/approvals", end: false },
];

/**
 * The first INLINE items sit in the bar; the rest open from More. Five labels, More, the bell, the
 * scope chip and the account button fit at 1024px; the data pill only joins from 1280px (TopBar).
 */
const INLINE = 5;

const linkCls = cn(
  "inline-flex h-8 w-max items-center justify-center rounded-lg px-2.5 text-sm font-medium transition-colors",
  "text-fg-muted hover:bg-surface-elevated hover:text-fg-base",
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
  "data-[active]:bg-surface-panel data-[active]:text-fg-base data-[active]:shadow-sm data-[active]:ring-1 data-[active]:ring-border-subtle",
  "data-[state=open]:bg-surface-elevated"
);

export function NavigationMenuWithActiveItem() {
  const location = useLocation();
  const { role } = useRole();
  const [open, setOpen] = useState(false);
  const visibleItems = navigationMenuItems.filter((item) => canOpen(role, item.href));
  const isActive = (item: NavItem) =>
    item.end ? location.pathname === item.href : location.pathname.startsWith(item.href) && item.href !== "/";
  const inline = visibleItems.slice(0, INLINE);
  const more = visibleItems.slice(INLINE);
  const moreActive = more.some(isActive);

  return (
    <NavigationMenu>
      <NavigationMenuList className="space-x-0.5">
        {inline.map((item) => (
          <NavigationMenuItem key={item.title}>
            <NavigationMenuLink active={isActive(item)} asChild className={linkCls}>
              <NavLink to={item.href} end={item.end} className="flex flex-row items-center">
                {item.title}
              </NavLink>
            </NavigationMenuLink>
          </NavigationMenuItem>
        ))}
        {more.length > 0 && (
          <NavigationMenuItem>
            <Popover.Root open={open} onOpenChange={setOpen}>
              <Popover.Trigger
                data-active={moreActive ? "" : undefined}
                className={cn(linkCls, "gap-1")}
                aria-label="more pages"
              >
                More <ChevronDown aria-hidden className="size-3.5" />
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 min-w-[180px] overflow-hidden rounded-xl border border-border-default bg-surface-panel p-1 shadow-pop"
                >
                  {more.map((item) => (
                    <NavLink
                      key={item.title}
                      to={item.href}
                      end={item.end}
                      onClick={() => setOpen(false)}
                      className={cn(
                        "block rounded-lg px-3 py-2 text-sm font-medium hover:bg-surface-elevated",
                        isActive(item) ? "bg-surface-elevated text-fg-base" : "text-fg-muted"
                      )}
                    >
                      {item.title}
                    </NavLink>
                  ))}
                </Popover.Content>
              </Popover.Portal>
            </Popover.Root>
          </NavigationMenuItem>
        )}
      </NavigationMenuList>
    </NavigationMenu>
  );
}
