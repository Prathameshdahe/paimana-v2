import { Home, Terminal, Box, ClipboardCheck, ListChecks, Inbox } from "lucide-react";
import { NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/formatters";
import { useRole, type Role } from "@/lib/auth/RoleContext";
import {
  NavigationMenu,
  NavigationMenuItem,
  NavigationMenuLink,
  NavigationMenuList,
} from "@/components/ui/navigation-menu";

const navigationMenuItems = [
  { title: "HOME", href: "/", icon: Home, end: true, roles: undefined as Role[] | undefined },
  { title: "COMMAND", href: "/command", icon: Terminal, end: false, roles: undefined },
  { title: "SANDBOX", href: "/sandbox", icon: Box, end: false, roles: undefined },
  { title: "AUDIT", href: "/audit", icon: ClipboardCheck, end: false, roles: undefined },
  {
    title: "WORKERS",
    href: "/workers",
    icon: ListChecks,
    end: false,
    roles: ["ipmd_analyst", "ministry_official"] as Role[],
  },
  {
    title: "APPROVALS",
    href: "/approvals",
    icon: Inbox,
    end: false,
    roles: ["ipmd_analyst", "ministry_official", "agency_official"] as Role[],
  },
];

export function NavigationMenuWithActiveItem() {
  const location = useLocation();
  const { role } = useRole();
  const visibleItems = navigationMenuItems.filter(
    (item) => !item.roles || (role && item.roles.includes(role))
  );

  return (
    <NavigationMenu>
      <NavigationMenuList className="space-x-8">
        {visibleItems.map((item) => {
          // Determine if active based on current location and whether it requires exact match (end)
          const isActive = item.end
            ? location.pathname === item.href
            : location.pathname.startsWith(item.href) && item.href !== "/";

          return (
            <NavigationMenuItem key={item.title}>
              <NavigationMenuLink
                active={isActive}
                asChild
                className={cn(
                  "group relative inline-flex h-9 w-max items-center justify-center px-0.5 py-2 font-sans font-semibold text-[13px] tracking-widest transition-colors",
                  "before:absolute before:inset-x-0 before:bottom-0 before:h-[2px] before:scale-x-0 before:bg-fg-base before:transition-transform",
                  "hover:text-fg-muted hover:before:scale-x-100",
                  "focus:text-fg-base focus:outline-none focus:before:scale-x-100",
                  "disabled:pointer-events-none disabled:opacity-50",
                  "data-[active]:bg-transparent data-[state=open]:before:scale-x-100 data-[active]:before:scale-x-100 data-[active]:text-fg-base",
                  "text-fg-dimmed",
                  "hover:bg-transparent focus:bg-transparent active:bg-transparent"
                )}
              >
                <NavLink to={item.href} end={item.end} className="flex flex-row items-center gap-2">
                  <item.icon className="h-4 w-4 shrink-0 opacity-70" />
                  {item.title}
                </NavLink>
              </NavigationMenuLink>
            </NavigationMenuItem>
          );
        })}
      </NavigationMenuList>
    </NavigationMenu>
  );
}
