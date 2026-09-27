import { useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import * as Popover from "@radix-ui/react-popover";
import { cn } from "@/lib/formatters";
import { useRole, type Role } from "@/lib/auth/RoleContext";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";

type NavItem = { title: string; href: string; end: boolean; roles?: Role[] };

const navigationMenuItems: NavItem[] = [
  { title: "HOME", href: "/", end: true },
  { title: "COMMAND", href: "/command", end: false },
  { title: "EXTERNAL FACTORS", href: "/external", end: false },
  { title: "BOTTLENECKS", href: "/bottlenecks", end: false },
  { title: "AGENCIES", href: "/agencies", end: false },
  { title: "RADAR", href: "/radar", end: false },
  { title: "MODELS", href: "/models", end: false },
  { title: "WORKERS", href: "/workers", end: false, roles: ["ipmd_analyst", "ministry_official"] },
  { title: "APPROVALS", href: "/approvals", end: false, roles: ["ipmd_analyst", "ministry_official", "agency_official"] },
];

/**
 * The first INLINE items sit in the bar; the rest open from MORE. Four labels, MORE, the bell and
 * the role switch fit next to the asof ticker at 1024px (measured: the bar has ~545px for links);
 * the ticker grows with the width, so the split stays the same at every size.
 */
const INLINE = 4;

const linkCls = cn(
  "group relative inline-flex h-9 w-max items-center justify-center px-0.5 py-2 font-sans font-semibold text-[13px] tracking-widest transition-colors",
  "before:absolute before:inset-x-0 before:bottom-0 before:h-[2px] before:scale-x-0 before:bg-fg-base before:transition-transform",
  "hover:text-fg-muted hover:before:scale-x-100",
  "focus:text-fg-base focus:outline-none focus:before:scale-x-100",
  "disabled:pointer-events-none disabled:opacity-50",
  "data-[active]:bg-transparent data-[state=open]:before:scale-x-100 data-[active]:before:scale-x-100 data-[active]:text-fg-base",
  "text-fg-dimmed",
  "hover:bg-transparent focus:bg-transparent active:bg-transparent"
);

export function NavigationMenuWithActiveItem() {
  const location = useLocation();
  const { role } = useRole();
  const [open, setOpen] = useState(false);
  const visibleItems = navigationMenuItems.filter(
    (item) => !item.roles || (role && item.roles.includes(role))
  );
  const isActive = (item: NavItem) =>
    item.end ? location.pathname === item.href : location.pathname.startsWith(item.href) && item.href !== "/";
  const inline = visibleItems.slice(0, INLINE);
  const more = visibleItems.slice(INLINE);
  const moreActive = more.some(isActive);

  return (
    <NavigationMenu>
      <NavigationMenuList className="space-x-3 xl:space-x-5 2xl:space-x-6">
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
                MORE <span aria-hidden className="text-[10px]">▾</span>
              </Popover.Trigger>
              <Popover.Portal>
                <Popover.Content
                  align="end"
                  sideOffset={6}
                  className="z-50 min-w-[180px] border border-border-default bg-surface-panel py-1 shadow-lg"
                >
                  {more.map((item) => (
                    <NavLink
                      key={item.title}
                      to={item.href}
                      end={item.end}
                      onClick={() => setOpen(false)}
                      className={cn(
                        "block px-4 py-2 font-sans text-[12px] font-semibold tracking-widest hover:bg-surface-elevated",
                        isActive(item) ? "text-fg-base border-l-2 border-fg-base" : "text-fg-dimmed"
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
