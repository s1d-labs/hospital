function scalar(value) {
  return ['number', 'string'].includes(typeof value) ? String(value).trim() : '';
}

function label(value) {
  return scalar(value) || scalar(value?.name) || scalar(value?.locName);
}

function related(items, pick) {
  return Array.isArray(items) ? [...new Set(items.map(pick).filter(Boolean))].join(' | ') : '';
}

// Only serialize named directory fields. A JSON list inside a CSV cell keeps each
// registration, qualification, shift or job attached to its own details.
function detailList(items, project) {
  if (!Array.isArray(items)) return '';
  const details = items.filter(item => item && typeof item === 'object').map(project)
    .map(row => Object.fromEntries(Object.entries(row).filter(([, value]) => value !== '')))
    .filter(row => Object.keys(row).length);
  return details.length ? JSON.stringify(details) : '';
}

function flag(value) {
  return typeof value === 'boolean' ? String(value) : scalar(value);
}

function labels(value) {
  const one = entry => label(entry) || scalar(entry?.specName) || scalar(entry?.specialityName) || label(entry?.specialityId);
  return Array.isArray(value) ? related(value, one) : one(value);
}

function hospital(r) {
  const [lat, lon] = scalar(r.geolocation).split(',');
  const capacity = key => related(r.medicalInfraRequestDTO, entry => scalar(entry?.[key]));
  return {
    hfr_id: scalar(r.alternateId), hospital: scalar(r.facName), facility_type: label(r.facilityType),
    ownership: label(r.facOwnership), street_address: scalar(r.address1), locality: label(r.vilCityTown),
    district: label(r.district), state: label(r.state), pincode: scalar(r.pincode ?? r.pinCode),
    latitude: scalar(r.facilityLat) || scalar(lat), longitude: scalar(r.facilityLong) || scalar(lon),
    specialties: related(r.specialityDtls, s => scalar(s?.specName)),
    total_beds: capacity('totalBeds'),
    approval_status: scalar(r.status), system_of_medicine: labels(r.systemOfMedicine),
    service_types: labels(r.typeOfService),
    opening_hours: detailList(r.operationRequestDTO, shift => ({
      day: scalar(shift.day ?? shift.id?.day), open_24_hours: flag(shift.hrs24), morning_open: scalar(shift.morOpenTime), morning_close: scalar(shift.morCloseTime),
      evening_open: scalar(shift.eveOpenTime), evening_close: scalar(shift.eveCloseTime),
    })),
    days_of_operation: scalar(r.daysOfOperation), hours_of_operation: scalar(r.hoursOfOperation),
    inpatient_beds_with_oxygen: capacity('ipdBedsWithO2'), inpatient_beds_without_oxygen: capacity('ipdBedsWithoutO2'),
    icu_beds_with_ventilator: capacity('icuBedsWithVent'), icu_beds_without_ventilator: capacity('icuBedsWithoutVent'),
    hdu_beds_with_ventilator: capacity('hduBedsWithFuncVent'), hdu_beds_without_ventilator: capacity('hduBedsWithoutVent'),
    ventilators: capacity('ventillators'),
    pmjay_id: scalar(r.pmjayHospitalId ?? r.abPmjayHospitalId ?? r.pmjayId), cghs_id: scalar(r.cghsHospitalId ?? r.cghsId),
    echs_id: scalar(r.echsHospitalId), rohini_id: scalar(r.rohiniId), nin_id: scalar(r.nhrrFacilityId), cea_id: scalar(r.ceaId),
    hmis_code: scalar(r.hmisCode ?? r.hmisId),
  };
}

function doctor(r) {
  return {
    hpr_id: scalar(r.hprIdNumber) || scalar(r.hprId), doctor: scalar(r.name),
    system_of_medicine: label(r.systemOfMedicine),
    registrations: related(r.hprRgistraionDetails, entry =>
      [label(entry?.medicalCouncilObject), scalar(entry?.medicalCouncilRegistrationNo)].filter(Boolean).join(' / ')),
    qualifications: related(r.doctorMedicalQualifications, entry => label(entry?.courseId)),
    workplace_hfr_ids: related(r.hprWorkDetails, entry => scalar(entry?.facilityId)),
    specialties: labels(r.hprSpecialitys ?? r.specialities ?? r.speciality),
    experience_years: scalar(r.workExperienceInYear),
    registration_details: detailList(r.hprRgistraionDetails, entry => ({
      council: label(entry.medicalCouncilObject), number: scalar(entry.medicalCouncilRegistrationNo),
      verified: entry.councilStatus == null || entry.councilStatus === '' ? '' : String(String(entry.councilStatus) === '1'),
      registration_date: scalar(entry.medicalRegistrationDate), renewal_due: scalar(entry.dueDate ?? entry.renewableTill), renewable: flag(entry.isRenewable),
    })),
    qualification_details: detailList(r.doctorMedicalQualifications, entry => ({
      degree: label(entry.courseId), year: scalar(entry.qualificationYear),
      college: label(entry.collegeId), university: label(entry.universityId),
    })),
    workplace_details: detailList(r.hprWorkDetails, entry => ({
      facility_id: scalar(entry.facilityId), facility: scalar(entry.facilityName),
      role: scalar(entry.designationWithOrganisation), current: flag(entry.current ?? entry.currentlyWorking),
    })),
  };
}

export { doctor, hospital };
