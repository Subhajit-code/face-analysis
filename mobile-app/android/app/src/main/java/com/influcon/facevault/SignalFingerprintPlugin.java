package com.influcon.facevault;

import android.Manifest;
import android.content.pm.PackageManager;
import android.net.wifi.ScanResult;
import android.net.wifi.WifiManager;
import android.telephony.CellInfo;
import android.telephony.CellInfoGsm;
import android.telephony.CellInfoLte;
import android.telephony.CellInfoWcdma;
import android.telephony.TelephonyManager;
import android.os.Build;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.util.List;

/**
 * Reads real nearby WiFi access point IDs (BSSIDs) and the serving cell tower ID.
 * This is what the GPS-spoofing-resistant "signal fingerprint" is built from: a fake-GPS
 * app can move the coordinates a webview reports, but it cannot alter which radio
 * signals the device's hardware actually hears, so the backend can cross-check that the
 * reported location is consistent with what the device physically picked up nearby.
 */
@CapacitorPlugin(
    name = "SignalFingerprint",
    permissions = {
        @Permission(strings = { Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION }, alias = "location"),
        @Permission(strings = { Manifest.permission.ACCESS_WIFI_STATE, Manifest.permission.CHANGE_WIFI_STATE }, alias = "wifi"),
        @Permission(strings = { Manifest.permission.READ_PHONE_STATE }, alias = "phoneState")
    }
)
public class SignalFingerprintPlugin extends Plugin {

    @PluginMethod
    public void scanNearby(PluginCall call) {
        if (getPermissionState("location") != com.getcapacitor.PermissionState.GRANTED
            || getPermissionState("wifi") != com.getcapacitor.PermissionState.GRANTED) {
            requestPermissionForAliases(new String[] { "location", "wifi", "phoneState" }, call, "scanNearbyCallback");
            return;
        }
        performScan(call);
    }

    @PermissionCallback
    private void scanNearbyCallback(PluginCall call) {
        if (getPermissionState("location") == com.getcapacitor.PermissionState.GRANTED
            && getPermissionState("wifi") == com.getcapacitor.PermissionState.GRANTED) {
            performScan(call);
        } else {
            call.reject("Location/WiFi permission denied. Cannot build signal fingerprint.");
        }
    }

    private void performScan(PluginCall call) {
        JSObject result = new JSObject();
        JSArray wifiArray = new JSArray();

        try {
            WifiManager wifiManager = (WifiManager) getContext().getApplicationContext().getSystemService(android.content.Context.WIFI_SERVICE);
            if (wifiManager != null) {
                if (!wifiManager.isWifiEnabled()) {
                    wifiManager.setWifiEnabled(true);
                }
                wifiManager.startScan();
                List<ScanResult> scanResults = wifiManager.getScanResults();
                if (scanResults != null) {
                    for (ScanResult sr : scanResults) {
                        JSObject ap = new JSObject();
                        ap.put("ssid", sr.SSID != null ? sr.SSID : "");
                        ap.put("bssid", sr.BSSID != null ? sr.BSSID : "");
                        ap.put("rssi", sr.level);
                        wifiArray.put(ap);
                    }
                }
            }
        } catch (SecurityException se) {
            call.reject("WiFi scan permission denied: " + se.getMessage());
            return;
        }

        JSArray towerArray = new JSArray();
        try {
            TelephonyManager tm = (TelephonyManager) getContext().getApplicationContext().getSystemService(android.content.Context.TELEPHONY_SERVICE);
            if (tm != null && getPermissionState("phoneState") == com.getcapacitor.PermissionState.GRANTED) {
                List<CellInfo> cellInfoList = tm.getAllCellInfo();
                if (cellInfoList != null) {
                    for (CellInfo ci : cellInfoList) {
                        JSObject tower = new JSObject();
                        if (ci instanceof CellInfoLte) {
                            CellInfoLte lte = (CellInfoLte) ci;
                            tower.put("type", "LTE");
                            tower.put("cellId", lte.getCellIdentity().getCi());
                            tower.put("pci", lte.getCellIdentity().getPci());
                            tower.put("tac", lte.getCellIdentity().getTac());
                            tower.put("registered", ci.isRegistered());
                            towerArray.put(tower);
                        } else if (ci instanceof CellInfoGsm) {
                            CellInfoGsm gsm = (CellInfoGsm) ci;
                            tower.put("type", "GSM");
                            tower.put("cellId", gsm.getCellIdentity().getCid());
                            tower.put("lac", gsm.getCellIdentity().getLac());
                            tower.put("registered", ci.isRegistered());
                            towerArray.put(tower);
                        } else if (ci instanceof CellInfoWcdma) {
                            CellInfoWcdma wcdma = (CellInfoWcdma) ci;
                            tower.put("type", "WCDMA");
                            tower.put("cellId", wcdma.getCellIdentity().getCid());
                            tower.put("lac", wcdma.getCellIdentity().getLac());
                            tower.put("registered", ci.isRegistered());
                            towerArray.put(tower);
                        }
                    }
                }
            }
        } catch (SecurityException se) {
            // Cell info is best-effort; WiFi fingerprint alone is still useful.
        }

        result.put("wifiAccessPoints", wifiArray);
        result.put("cellTowers", towerArray);
        call.resolve(result);
    }
}
