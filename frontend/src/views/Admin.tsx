import { Page, PageHeader } from '@/components/layout/Page'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { Requests } from '@/views/admin/Requests'
import { Users } from '@/views/admin/Users'
import { Audit } from '@/views/admin/Audit'

/**
 * Administration (/admin; administrators only, lib/auth/access.ts canAdmin): three plain, dense tabs over
 * /api/admin/* — sign-up requests to approve or reject, accounts to search, correct, disable and reset, and the
 * audit log. Nothing here touches projects, models or scores: an administrator manages people, not data.
 */
export function Admin() {
  return (
    <Page>
      <PageHeader
        title="Administration"
        subtitle="Sign-up requests, accounts and the audit log"
        info="Every action here is written to the audit log with your account and address. An administrator cannot disable or demote their own account."
      />
      <Tabs defaultValue="requests">
        <TabsList aria-label="Administration">
          <TabsTrigger value="requests">Requests</TabsTrigger>
          <TabsTrigger value="users">Users</TabsTrigger>
          <TabsTrigger value="audit">Audit</TabsTrigger>
        </TabsList>
        <TabsContent value="requests"><Requests /></TabsContent>
        <TabsContent value="users"><Users /></TabsContent>
        <TabsContent value="audit"><Audit /></TabsContent>
      </Tabs>
    </Page>
  )
}
