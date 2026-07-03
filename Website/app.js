import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { createClient } from "https://esm.sh/@supabase/supabase-js@2";
import { SUPABASE_ANON_KEY, SUPABASE_URL } from "./supabase-config.js";

const canvas = document.querySelector("#scene");
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 100);
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
const clock = new THREE.Clock();
const root = new THREE.Group();

camera.position.set(4.8, 2.2, 6.6);
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.15;

const controls = new OrbitControls(camera, renderer.domElement);
controls.enableDamping = true;
controls.enablePan = false;
controls.enableZoom = false;
controls.autoRotate = true;
controls.autoRotateSpeed = 0.65;
controls.target.set(0, 0.55, 0);

scene.add(root);
scene.add(new THREE.HemisphereLight(0xffffff, 0x111111, 2.5));

const keyLight = new THREE.DirectionalLight(0xffffff, 3.4);
keyLight.position.set(4, 6, 3);
scene.add(keyLight);

const rimLight = new THREE.PointLight(0xc7ff45, 110, 18);
rimLight.position.set(-4, 2.5, 3);
scene.add(rimLight);

const blueLight = new THREE.PointLight(0x8edfff, 70, 16);
blueLight.position.set(4, 0.8, -3);
scene.add(blueLight);

const floor = new THREE.Mesh(
  new THREE.CircleGeometry(5.4, 128),
  new THREE.MeshStandardMaterial({
    color: 0x0b0b0a,
    metalness: 0.2,
    roughness: 0.62,
    transparent: true,
    opacity: 0.62
  })
);
floor.rotation.x = -Math.PI / 2;
floor.position.y = -0.82;
scene.add(floor);

function material(color, options = {}) {
  return new THREE.MeshStandardMaterial({
    color,
    metalness: options.metalness ?? 0.18,
    roughness: options.roughness ?? 0.45,
    emissive: options.emissive ?? 0x000000,
    emissiveIntensity: options.emissiveIntensity ?? 0
  });
}

function addBox(size, position, mat) {
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(...size), mat);
  mesh.position.set(...position);
  root.add(mesh);
}

function buildFallbackModel() {
  addBox([2.35, 1.55, 0.24], [0, 0.92, 0], material(0xdad4bf, { roughness: 0.56 }));
  addBox([1.86, 1.02, 0.035], [0, 0.98, 0.14], material(0x06120f, { emissive: 0x0df995, emissiveIntensity: 0.45 }));
  addBox([1.45, 0.16, 0.04], [0, 0.52, 0.17], material(0xf8d94a, { emissive: 0xf8d94a, emissiveIntensity: 0.7 }));
  addBox([0.34, 0.7, 0.24], [0, -0.1, -0.02], material(0xc9c1aa));
  addBox([1.25, 0.18, 0.82], [0, -0.52, 0.06], material(0xc9c1aa));
  addBox([1.04, 1.6, 1.1], [2.02, 0.1, -0.1], material(0xcfc7b0));
  addBox([2.25, 0.16, 0.78], [-0.15, -0.73, 1.25], material(0xbdb49d));
}

function loadModel() {
  const loader = new GLTFLoader();
  loader.setPath("./assets/");
  loader.load(
    "retro pc.glb",
    (gltf) => {
      const model = gltf.scene;
      const box = new THREE.Box3().setFromObject(model);
      const size = box.getSize(new THREE.Vector3());
      const center = box.getCenter(new THREE.Vector3());
      const scale = 3.9 / Math.max(size.x, size.y, size.z);
      model.scale.setScalar(scale);
      model.position.sub(center.multiplyScalar(scale));
      model.position.y += 0.28;
      root.add(model);
    },
    undefined,
    buildFallbackModel
  );
}

function resize() {
  const { clientWidth, clientHeight } = canvas.parentElement;
  camera.aspect = clientWidth / clientHeight;
  camera.updateProjectionMatrix();
  renderer.setSize(clientWidth, clientHeight, false);
}

function animate() {
  const elapsed = clock.getElapsedTime();
  root.position.y = Math.sin(elapsed * 1.05) * 0.055;
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(animate);
}

window.addEventListener("resize", resize);
resize();
loadModel();
animate();

const founderEmails = ["rawjanihasan@gmaill.com", "rawjanihasan@gmail.com"];
const adminLogin = { email: "admin", password: "admin", plan: "Pro Trial" };
const STRIPE_PRO_CHECKOUT_URL = "https://buy.stripe.com/REPLACE_WITH_PRO_PAYMENT_LINK";
const STRIPE_TRIAL_CHECKOUT_URL = "https://buy.stripe.com/REPLACE_WITH_TRIAL_PAYMENT_LINK";
const cleanSupabaseUrl = String(SUPABASE_URL || "")
  .replace(/\/rest\/v1\/?$/, "")
  .replace(/\/+$/, "");
const supabaseConfigured =
  cleanSupabaseUrl &&
  SUPABASE_ANON_KEY &&
  !cleanSupabaseUrl.includes("YOUR_") &&
  !SUPABASE_ANON_KEY.includes("YOUR_");
const supabase = supabaseConfigured ? createClient(cleanSupabaseUrl, SUPABASE_ANON_KEY) : null;
const authModal = document.querySelector("#authModal");
const authTitle = document.querySelector("#authTitle");
const authEyebrow = document.querySelector("#authEyebrow");
const authCopy = document.querySelector("#authCopy");
const authSubmit = document.querySelector("#authSubmit");
const authMessage = document.querySelector("#authMessage");
const authEmail = document.querySelector("#authEmail");
const authPassword = document.querySelector("#authPassword");
const authPasswordConfirm = document.querySelector("#authPasswordConfirm");
const resetPasswordBtn = document.querySelector("#resetPasswordBtn");
const authSwitchBtn = document.querySelector("#authSwitchBtn");
const googleSignInBtn = document.querySelector("#googleSignInBtn");
const authCloseBtn = document.querySelector("#authCloseBtn");
const signOutBtn = document.querySelector("#signOutBtn");
const planModal = document.querySelector("#planModal");
const planCloseBtn = document.querySelector("#planCloseBtn");
const checkoutPlan = document.querySelector("#checkoutPlan");
const stripeCheckoutBtn = document.querySelector("#stripeCheckoutBtn");
const trialCheckoutBtn = document.querySelector("#trialCheckoutBtn");
const paymentMethodButtons = document.querySelectorAll("[data-payment-method]");
const accountEmail = document.querySelector("#accountEmail");
const accountPlan = document.querySelector("#accountPlan");
let authMode = "signin";
let afterAuth = null;
let currentAccount = null;
let selectedPaymentMethod = "card";

function cacheAccount(email, plan) {
  localStorage.setItem(
    "highlightlyAccount",
    JSON.stringify({ email, plan, updatedAt: new Date().toISOString() })
  );
  accountEmail.textContent = email;
  accountPlan.textContent = plan;
}

function getCachedAccount() {
  try {
    return JSON.parse(localStorage.getItem("highlightlyAccount") || "null");
  } catch {
    return null;
  }
}

function planForEmail(email) {
  return founderEmails.includes(email?.toLowerCase()) ? "Founder Pro" : "Free";
}

function setSignedIn(user) {
  if (!user?.email) return;
  const metadataPlan = user.user_metadata?.highlightly_plan;
  const account = { email: user.email, plan: metadataPlan || planForEmail(user.email), id: user.id };
  currentAccount = account;
  cacheAccount(account.email, account.plan);
  document.body.classList.add("is-authed");
  accountEmail.textContent = account.email;
  accountPlan.textContent = account.plan;
  unlockDownload(account);
}

function setSignedOut() {
  currentAccount = null;
  document.body.classList.remove("is-authed");
  accountEmail.textContent = "Signed out";
  accountPlan.textContent = "No plan";
  downloadStatus.textContent = "Verify your email to unlock downloads.";
  downloadStatus.style.color = "#66665f";
}

document.querySelectorAll("[data-open-auth]").forEach((button) => {
  button.addEventListener("click", () => {
    authMode = button.dataset.openAuth;
    openAuthModal();
  });
});

function openAuthModal(callback = null) {
  afterAuth = callback;
  const creating = authMode === "create";
  authModal.dataset.mode = authMode;
  authEyebrow.textContent = creating ? "Create account" : "Welcome back";
  authTitle.textContent = creating ? "Create your Highlightly account" : "Sign in to Highlightly";
  authCopy.textContent = creating
    ? "Choose a password. Supabase will email you a verification link before downloads unlock."
    : "Sign in with your verified email and password.";
  authSubmit.textContent = creating ? "Create account" : "Sign in";
  authEmail.value = currentAccount?.email || getCachedAccount()?.email || authEmail.value;
  authPassword.value = "";
  authPasswordConfirm.value = "";
  authPassword.autocomplete = creating ? "new-password" : "current-password";
  authPasswordConfirm.required = creating;
  authSwitchBtn.textContent = creating ? "Already have an account? Sign in" : "Need an account? Create one";
  authMessage.textContent = "";
  authModal.showModal();
  setTimeout(() => authEmail.focus(), 80);
}

function requireVerified(callback) {
  if (currentAccount?.email) {
    callback(currentAccount);
    return;
  }
  authMode = "signin";
  openAuthModal(callback);
}

authCloseBtn.addEventListener("click", () => {
  authModal.close();
  authMessage.textContent = "";
  afterAuth = null;
});

document.querySelector("#authForm").addEventListener("submit", (event) => {
  event.preventDefault();
  handleAuthSubmit();
});

async function handleAuthSubmit() {
  const email = authEmail.value.trim().toLowerCase();
  const password = authPassword.value;
  authMessage.style.color = "#c7ff45";

  if (authMode === "signin" && email === adminLogin.email && password === adminLogin.password) {
    setSignedIn({
      id: "local-admin",
      email: "admin",
      user_metadata: { highlightly_plan: adminLogin.plan }
    });
    authMessage.textContent = "Admin account signed in.";
    finishAuth(false);
    return;
  }

  if (!email) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Enter your email.";
    return;
  }

  if (password.length < 8) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Password must be at least 8 characters.";
    return;
  }

  if (!supabase) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Add the Supabase project URL and full publishable key in supabase-config.js.";
    return;
  }

  authSubmit.disabled = true;
  try {
    if (authMode === "create") {
      if (password !== authPasswordConfirm.value) throw new Error("Passwords do not match.");
      const { data, error } = await supabase.auth.signUp({
        email,
        password,
        options: { emailRedirectTo: window.location.origin }
      });
      if (error) throw error;
      if (data.session?.user) {
        setSignedIn(data.session.user);
        authMessage.textContent = "Account created.";
        finishAuth(true);
      } else {
        authMessage.textContent = "Check your inbox and confirm your email. After confirming, sign in and choose your plan.";
      }
      return;
    }

    const { data, error } = await supabase.auth.signInWithPassword({ email, password });
    if (error) throw error;
    setSignedIn(data.user);
    authMessage.textContent = "Signed in.";
    finishAuth(!data.user?.user_metadata?.highlightly_plan);
  } catch (error) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = error.message;
  } finally {
    authSubmit.disabled = false;
  }
}

function finishAuth(showPlans = false) {
  setTimeout(() => {
    authModal.close();
    if (afterAuth) afterAuth(currentAccount);
    afterAuth = null;
    if (showPlans && currentAccount?.email) openPlanModal();
  }, 350);
}

function openPlanModal() {
  planModal.showModal();
}

function setLocalPlan(plan) {
  if (!currentAccount?.email) return;
  currentAccount.plan = founderEmails.includes(currentAccount.email.toLowerCase()) ? "Founder Pro" : plan;
  cacheAccount(currentAccount.email, currentAccount.plan);
  accountPlan.textContent = currentAccount.plan;
}

async function savePlan(plan) {
  setLocalPlan(plan);
  if (supabase) {
    await supabase.auth.updateUser({ data: { highlightly_plan: plan } }).catch(() => {});
  }
}

function openStripe(url, plan) {
  if (!url || url.includes("REPLACE_WITH")) {
    checkoutMessage.style.color = "#ff5a6a";
    checkoutMessage.textContent = "Add your Stripe Payment Link in app.js first.";
    return;
  }
  checkoutMessage.style.color = "#c7ff45";
  checkoutMessage.textContent = `Opening Stripe Checkout for ${paymentMethodLabel(selectedPaymentMethod)}...`;
  savePlan(plan);
  window.location.href = url;
}

function paymentMethodLabel(method) {
  if (method === "cashapp") return "Cash App Pay";
  if (method === "bank") return "bank payment";
  return "card payment";
}

authSwitchBtn.addEventListener("click", () => {
  authMode = authMode === "create" ? "signin" : "create";
  openAuthModal(afterAuth);
});

googleSignInBtn.addEventListener("click", async () => {
  if (!supabase) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Supabase is not configured yet.";
    return;
  }
  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: { redirectTo: window.location.origin }
  });
  if (error) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = error.message;
  }
});

resetPasswordBtn.addEventListener("click", async () => {
  const email = authEmail.value.trim().toLowerCase();
  if (!email) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Enter your email first.";
    return;
  }
  if (!supabase) {
    authMessage.style.color = "#ff5a6a";
    authMessage.textContent = "Supabase is not configured yet.";
    return;
  }
  const { error } = await supabase.auth.resetPasswordForEmail(email, {
    redirectTo: window.location.origin
  });
  authMessage.style.color = error ? "#ff5a6a" : "#c7ff45";
  authMessage.textContent = error ? error.message : "Password reset email sent.";
});

signOutBtn.addEventListener("click", async () => {
  if (supabase) await supabase.auth.signOut();
  localStorage.removeItem("highlightlyAccount");
  setSignedOut();
});

const checkoutMessage = document.querySelector("#checkoutMessage");

function showCheckout(plan) {
  checkoutPlan.textContent = plan === "Trial" ? "Pro trial - 3 days" : "Pro monthly - $10";
  window.location.hash = "checkout";
}

stripeCheckoutBtn.addEventListener("click", () => {
  requireVerified(() => openStripe(STRIPE_PRO_CHECKOUT_URL, "Pro"));
});

trialCheckoutBtn.addEventListener("click", () => {
  requireVerified(() => openStripe(STRIPE_TRIAL_CHECKOUT_URL, "Pro Trial"));
});

paymentMethodButtons.forEach((button) => {
  button.addEventListener("click", () => {
    selectedPaymentMethod = button.dataset.paymentMethod;
    paymentMethodButtons.forEach((item) => item.classList.toggle("active", item === button));
    checkoutMessage.style.color = "#c7ff45";
    checkoutMessage.textContent = `${paymentMethodLabel(selectedPaymentMethod)} selected. Stripe will show available secure payment fields.`;
  });
});

const downloadStatus = document.querySelector("#downloadStatus");
const downloadHref = "./downloads/Highlightly-Desktop-Access.txt";

function unlockDownload(account) {
  downloadStatus.textContent = `${account.email} verified. Download unlocked.`;
  downloadStatus.style.color = "#305e00";
}

function downloadDesktopApp(account) {
  unlockDownload(account);
  const link = document.createElement("a");
  link.href = downloadHref;
  link.download = "Highlightly-Desktop-Access.txt";
  document.body.append(link);
  link.click();
  link.remove();
}

document.querySelector("#openDownload").addEventListener("click", () => {
  requireVerified((account) => {
    unlockDownload(account);
    document.querySelector("#download").scrollIntoView({ behavior: "smooth" });
  });
});

document.querySelector("#downloadApp").addEventListener("click", () => {
  requireVerified(downloadDesktopApp);
});

document.querySelectorAll("[data-plan-choice]").forEach((button) => {
  button.addEventListener("click", () => {
    const plan = button.dataset.planChoice;
    requireVerified(async () => {
      if (plan === "Free") {
        await savePlan("Free");
        if (planModal.open) planModal.close();
        button.textContent = "Free access active";
        return;
      }
      if (planModal.open) planModal.close();
      showCheckout(plan);
    });
  });
});

planCloseBtn.addEventListener("click", () => planModal.close());

const savedAccount = getCachedAccount();
if (savedAccount?.email) {
  accountEmail.textContent = savedAccount.email;
  accountPlan.textContent = savedAccount.plan || "Free";
}

if (supabase) {
  supabase.auth.getSession().then(({ data }) => {
    if (data.session?.user) {
      setSignedIn(data.session.user);
      if (!data.session.user.user_metadata?.highlightly_plan) openPlanModal();
    }
  });

  supabase.auth.onAuthStateChange((event, session) => {
    if (session?.user) {
      setSignedIn(session.user);
      if ((event === "SIGNED_IN" || event === "USER_UPDATED") && !session.user.user_metadata?.highlightly_plan) {
        openPlanModal();
      }
    }
    else setSignedOut();
  });
}