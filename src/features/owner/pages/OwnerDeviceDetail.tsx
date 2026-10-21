import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import DeviceDetailPage from "../../devices/pages/DeviceDetailPage"

export default function OwnerDeviceDetail() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <DeviceDetailPage />
      </main>
    </div>
  )
}

