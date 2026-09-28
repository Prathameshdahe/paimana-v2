import { Page, PageHeader } from '@/components/layout/Page'
import { useSession } from '@/lib/auth/SessionContext'
import { can } from '@/lib/auth/access'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { Requests } from '@/views/admin/Requests'
import { Users } from '@/views/admin/Users'
import { Audit } from '@/views/admin/Audit'

/**
 * Administration (/admin; administrators only, lib/auth/access.ts canAdmin): plain, dense tabs over /api/admin/* —
 * sign-up requests to approve or reject and accounts to search, correct, disable and reset; the audit log is a third
 * tab for the developer only (canSeeAudit). Nothing here touches projects, models or scores: an administrator
 * manages people, not data.
 */
export function Admin() {
  const { role } = useSession()
  const audit = can(role, 'canSeeAudit')
  return (
    <Page>
      <PageHeader
        title="Administration"
        subtitle={audit ? 'Sign-up requests, accounts and the audit log' : 'Sign-up requests and accounts'}
        info="Every action here is written to the audit log with your account and address. An administrator cannot disable or demote their own account."
      />
      <Tabs defaultValue="requests">
        <TabsList aria-label="Administration">
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          {audit && <TabsTrigger value="audit">Audit</TabsTrigger>}
        </TabsList>
        <TabsContent value="requests"><Requests /></TabsContent>
        <TabsContent value="users"><Users /></TabsContent>
        {audit && <TabsContent value="audit"><Audit /></TabsContent>}
      </Tabs>
    </Page>
  )
}
