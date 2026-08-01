import React from 'react';
import { Navigate, Outlet } from 'react-router-dom';

const PrivateRoute: React.FC = () => {
  const userType = localStorage.getItem('user_type');
  const clientId = localStorage.getItem('client_id');
  const companyId = (localStorage.getItem('company_id') || localStorage.getItem('clinic_id'));

  if (!userType || !clientId || !companyId) {
    return <Navigate to="/" replace />;
  }

  return <Outlet />;
};

export default PrivateRoute;
