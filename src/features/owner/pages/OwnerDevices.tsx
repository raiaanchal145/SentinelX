import Sidebar from "../../../components/Sidebar"
import Topbar from "../../../components/Topbar"
import DevicesPage from "../../devices/pages/DevicesPage"

export default function OwnerDevices() {
  return (
    <div className="flex min-h-screen bg-canvas text-white">
      <Sidebar />
      <main className="min-w-0 flex-1">
        <Topbar />
        <DevicesPage />
      </main>
    </div>
  )
}

