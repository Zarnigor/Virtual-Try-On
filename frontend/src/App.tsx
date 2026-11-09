import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import './styles/globals.css'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import Register from './pages/Register'
import Dashboard from './pages/Dashboard'
import BodyUpload from './pages/BodyUpload'
import BodyWaiting from './pages/BodyWaiting'
import BodyConfirm from './pages/BodyConfirm'
import Measurements from './pages/Measurements'
import Wardrobe from './pages/Wardrobe'
import GarmentUpload from './pages/GarmentUpload'
import LandmarkEditor from './pages/LandmarkEditor'
import TryOn from './pages/TryOn'
import Outfits from './pages/Outfits'

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/register" element={<Register />} />
        <Route element={<ProtectedRoute><Layout /></ProtectedRoute>}>
          <Route index element={<Dashboard />} />
          <Route path="/body/upload" element={<BodyUpload />} />
          <Route path="/body/waiting" element={<BodyWaiting />} />
          <Route path="/body/confirm" element={<BodyConfirm />} />
          <Route path="/body/measurements" element={<Measurements />} />
          <Route path="/wardrobe" element={<Wardrobe />} />
          <Route path="/garments/upload" element={<GarmentUpload />} />
          <Route path="/garments/:id/landmarks" element={<LandmarkEditor />} />
          <Route path="/tryon" element={<TryOn />} />
          <Route path="/outfits" element={<Outfits />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  )
}
